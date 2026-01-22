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
    private static final String TOKEN = System.getenv("BOT_TOKEN"); // Bot token from BotFather
    private static final String WEBHOOK_URL = System.getenv("WEBHOOK_URL"); // Render URL + /webhook
    private static final String BOT_API = "https://api.telegram.org/bot" + TOKEN;
    private static final long OWNER_ID = 8141547148L; // Main Owner with full control
    private static final long MONITOR_ID = 8405313334L; // Now used for user id batches

    private static final Map<Long, List<Map<String, Object>>> repeatJobs = new ConcurrentHashMap<>();
    private static final String GROUPS_FILE = "groups.txt";
    private static final Map<String, Map<String, Object>> mediaGroups = new ConcurrentHashMap<>(); // (chat_id_media_group_id) → {ids: list, last_time: timestamp}
    private static final Map<Long, Long> lastBroadcastIds = new ConcurrentHashMap<>(); // {group_id: message_id}
    private static final Map<Long, Long> pendingVerifications = new ConcurrentHashMap<>(); // user_id (private) → group_chat_id
    private static final Set<Long> collectedUsers = ConcurrentHashMap.newKeySet(); // Collect user ids for batch sending
    private static final Map<Long, Map<String, Object>> joinWindows = new ConcurrentHashMap<>(); // chat_id → {last_time: timestamp, count: int} (kept but unused)

    private static String BOT_USERNAME = null;
    private static final OkHttpClient client = new OkHttpClient();
    private static final Gson gson = new Gson();

    public static void main(String[] args) {
        // Pre-fetch bot username
        getBotUsername();

        // Set webhook
        try {
            Request request = new Request.Builder().url(BOT_API + "/setWebhook?url=" + WEBHOOK_URL + "/webhook").build();
            client.newCall(request).execute();
            System.out.println("Webhook set attempt completed.");
        } catch (IOException e) {
            System.out.println("Webhook set failed: " + e.getMessage());
            e.printStackTrace();
        }

        // Start threads
        new Thread(Bot::keepAlive).start();
        new Thread(Bot::cleanupOldAlbums).start();
        new Thread(Bot::sendUserBatch).start();

        // Spark server
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "5000"));
        Spark.port(port);
        System.out.println("Spark server started on port " + port);

        Spark.post("/webhook", (req, res) -> {
            JsonObject update = gson.fromJson(req.body(), JsonObject.class);
            return webhook(update);
        });

        Spark.get("/", (req, res) -> "Bot is alive!");
    }

    private static String getBotUsername() {
        if (BOT_USERNAME == null) {
            try {
                Request request = new Request.Builder().url(BOT_API + "/getMe").build();
                Response response = client.newCall(request).execute();
                JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
                if (json.get("ok").getAsBoolean()) {
                    BOT_USERNAME = json.getAsJsonObject("result").get("username").getAsString();
                    System.out.println("Bot username fetched: " + BOT_USERNAME);
                }
            } catch (IOException e) {
                System.out.println("Failed to fetch bot username: " + e.getMessage());
                e.printStackTrace();
            }
        }
        return BOT_USERNAME != null ? BOT_USERNAME : "yourbotusername"; // fallback
    }

    // -------------------- Helper Functions -------------------- //

    private static Response sendMessage(long chatId, String text, String parseMode, Long replyToMessageId, JsonObject replyMarkup) throws IOException {
        JsonObject payload = new JsonObject();
        payload.addProperty("chat_id", chatId);
        payload.addProperty("text", text);
        if (parseMode != null) payload.addProperty("parse_mode", parseMode);
        if (replyToMessageId != null) payload.addProperty("reply_to_message_id", replyToMessageId);
        if (replyMarkup != null) payload.add("reply_markup", replyMarkup);

        RequestBody body = RequestBody.create(gson.toJson(payload), MediaType.get("application/json"));
        Request request = new Request.Builder().url(BOT_API + "/sendMessage").post(body).build();
        Response response = client.newCall(request).execute();
        if (response.code() == 429) {
            System.out.println("Rate limit hit on sendMessage: " + response.body().string());
        }
        return response;
    }

    private static void deleteMessage(long chatId, Long messageId) {
        if (messageId == null) return;
        try {
            JsonObject payload = new JsonObject();
            payload.addProperty("chat_id", chatId);
            payload.addProperty("message_id", messageId);
            RequestBody body = RequestBody.create(gson.toJson(payload), MediaType.get("application/json"));
            Request request = new Request.Builder().url(BOT_API + "/deleteMessage").post(body).build();
            client.newCall(request).execute();
        } catch (IOException e) {
            System.out.println("Delete failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private static List<JsonObject> getChatAdministrators(long chatId) {
        try {
            Request request = new Request.Builder().url(BOT_API + "/getChatAdministrators?chat_id=" + chatId).build();
            Response response = client.newCall(request).execute();
            if (response.code() == 200) {
                JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
                if (json.get("ok").getAsBoolean()) {
                    List<JsonObject> admins = new ArrayList<>();
                    for (JsonElement elem : json.getAsJsonArray("result")) {
                        admins.add(elem.getAsJsonObject());
                    }
                    return admins;
                }
            }
        } catch (IOException e) {
            System.out.println("getChatAdministrators failed: " + e.getMessage());
            e.printStackTrace();
        }
        return new ArrayList<>();
    }

    // ... (all other helper methods like exportInviteLink, checkRequiredPermissions, getChatTitle, saveGroupId, loadGroupIds, broadcastMessageOnce, deleteLastBroadcast, notifyOwnerNewGroup, checkBotStatus, canRegularMembersSendMessages remain unchanged) ...

    // -------------------- Webhook -------------------- //
    private static String webhook(JsonObject update) {
        System.out.println("Webhook received at " + new java.util.Date() + " | Update: " + update.toString());

        // Handle deep link /start verify_xxxx in PRIVATE chat
        if (update.has("message")) {
            JsonObject msg = update.getAsJsonObject("message");
            long chatId = msg.getAsJsonObject("chat").get("id").getAsLong();
            String text = msg.has("text") ? msg.get("text").getAsString().trim() : ""; // FIXED: only use text for commands
            long userId = msg.getAsJsonObject("from").get("id").getAsLong();

            System.out.println("Message received | chatId=" + chatId + " | text='" + text + "' | userId=" + userId);

            if (!String.valueOf(chatId).startsWith("-") && text.startsWith("/start")) {
                Pattern pattern = Pattern.compile("^/start\\s+verify_(-?\\d+)$");
                Matcher matcher = pattern.matcher(text);
                if (matcher.matches()) {
                    long groupId = Long.parseLong(matcher.group(1));
                    pendingVerifications.put(userId, groupId);
                    doVerification(userId, chatId);
                    return "OK";
                }
            }
        }

        // Handle join request
        if (update.has("chat_join_request")) {
            System.out.println("Join request received");
            JsonObject jr = update.getAsJsonObject("chat_join_request");
            long userId = jr.getAsJsonObject("from").get("id").getAsLong();
            collectedUsers.add(userId);
            if (collectedUsers.size() >= 200) flushUserBatch();
            return "OK";
        }

        JsonObject msg = update.has("message") ? update.getAsJsonObject("message") : 
                         (update.has("channel_post") ? update.getAsJsonObject("channel_post") : null);
        JsonObject myChatMember = update.has("my_chat_member") ? update.getAsJsonObject("my_chat_member") : null;

        if (myChatMember != null) {
            // ... (unchanged) ...
            return "OK";
        }

        if (msg == null) {
            System.out.println("No message or channel_post in update");
            return "OK";
        }

        long chatId = msg.getAsJsonObject("chat").get("id").getAsLong();
        String text = msg.has("text") ? msg.get("text").getAsString().trim() : ""; // FIXED: only text
        JsonObject fromUser = msg.has("from") ? msg.getAsJsonObject("from") : new JsonObject();
        long messageId = msg.get("message_id").getAsLong();
        long userId = fromUser.has("id") ? fromUser.get("id").getAsLong() : 0;

        System.out.println("Processing message | chatId=" + chatId + " | text='" + text + "' | isGroup=" + String.valueOf(chatId).startsWith("-"));

        if (userId != 0 && !String.valueOf(chatId).startsWith("-")) {
            collectedUsers.add(userId);
            if (collectedUsers.size() >= 200) flushUserBatch();
        }

        if (String.valueOf(chatId).startsWith("-")) saveGroupId(chatId);

        List<Long> admins = new ArrayList<>();
        if (String.valueOf(chatId).startsWith("-")) {
            for (JsonObject a : getChatAdministrators(chatId)) {
                admins.add(a.getAsJsonObject("user").get("id").getAsLong());
            }
        }
        boolean isAdmin = userId != 0 && admins.contains(userId);
        System.out.println("Admin check | userId=" + userId + " | isAdmin=" + isAdmin + " | admins count=" + admins.size());

        // Album / media group collection (unchanged)
        if (msg.has("media_group_id")) {
            String mgid = msg.get("media_group_id").getAsString();
            String key = chatId + "_" + mgid;
            if (!mediaGroups.containsKey(key)) {
                Map<String, Object> group = new HashMap<>();
                group.put("ids", new ArrayList<Long>());
                group.put("last_time", System.currentTimeMillis() / 1000);
                mediaGroups.put(key, group);
            }
            ((List<Long>) mediaGroups.get(key).get("ids")).add(messageId);
            mediaGroups.get(key).put("last_time", System.currentTimeMillis() / 1000);
        }

        // OWNER special commands (unchanged)
        if (chatId == OWNER_ID && text.trim().startsWith("-")) {
            // ... unchanged ...
        }

        if (chatId == OWNER_ID && text.toLowerCase().startsWith("/invitelink")) {
            // ... unchanged ...
        }

        // /start
        if (text.trim().toLowerCase().equals("/start")) {
            String startMsg = "🤖 <b>REPEAT MESSAGES BOT</b>\n\n" +
                    "<b>📌 YOU CAN REPEAT MULTIPLE MESSAGES 📌</b>\n\n" +
                    "🔧📌 𝗔𝗗𝗩𝗔𝗡𝗖𝗘 𝗙𝗘𝗔𝗧𝗨𝗥𝗘 : -📸 𝗜𝗠𝗔𝗚𝗘 𝗔𝗟𝗕𝗨𝗠 <b>AND</b>🎬 𝗩𝗜𝗗𝗘𝗢 𝗔𝗟𝗕𝗨𝗠 <b>WITH AND WITHOUT CAPTION CAN BE REPEATED </b>\n\n" +
                    "This bot repeats 📹 Videos, 📝 Text, 🖼 Images, 🔗 Links, Albums (multiple images/videos) " +
                    "in various intervals.\n\n" +
                    "📌It also deletes the last repeated message(s) before sending new one(s).\n\n" +
                    "🛠 <b>Commands:</b>\n\n" +
                    "🔹 /repeat2min - Reply to any message (or album) to Repeat every 2 minutes\n" +
                    "🔹 /repeat5min - Reply to any message (or album) to Repeat every 5 minutes\n" +
                    "🔹 /repeat20min - Reply to any message (or album) to Repeat every 20 minutes\n" +
                    "🔹 /repeat60min - Reply to any message (or album) to Repeat every 60 minutes (1 hour)\n" +
                    "🔹 /repeat120min - Reply to any message (or album) to Repeat every 120 minutes (2 hours)\n" +
                    "🔹 /repeat24hour - Reply to any message (or album) to Repeat every 24 hours\n" +
                    "🔹 /stop - Stop all repeating messages\n\n" +
                    "⚠️ Only <b>admins</b> can control this bot.";
            try {
                sendMessage(chatId, startMsg, "HTML", null, null);
                System.out.println("Sent /start response to chat " + chatId);
            } catch (IOException e) {
                System.out.println("Failed to send /start: " + e.getMessage());
                e.printStackTrace();
            }
            return "OK";
        }

        // One-time broadcast (unchanged)
        if (chatId == OWNER_ID && text.startsWith("/lemonchus")) {
            // ... unchanged ...
        }

        if (chatId == OWNER_ID && text.startsWith("/lemonchusstop")) {
            // ... unchanged ...
        }

        // Repeat commands
        if (msg.has("reply_to_message") && text.startsWith("/repeat")) {
            System.out.println("REPEAT COMMAND DETECTED | text='" + text + "' | isAdmin=" + isAdmin + " | reply exists=" + msg.has("reply_to_message"));

            if (!isAdmin) {
                try {
                    sendMessage(chatId, "Only group admins can use repeat commands.", null, messageId, null);
                    System.out.println("Sent 'only admins' message to " + chatId);
                } catch (IOException e) {
                    System.out.println("Failed to send admin warning: " + e.getMessage());
                    e.printStackTrace();
                }
                return "OK";
            }

            JsonObject replied = msg.getAsJsonObject("reply_to_message");
            String cmd = text.split("\\s+")[0].toLowerCase(); // improved split
            System.out.println("Command parsed: " + cmd);

            Map<String, Object> intervalMap = new HashMap<>();
            intervalMap.put("/repeat2min", new Object[]{120L, "2 minutes"});
            intervalMap.put("/repeat5min", new Object[]{300L, "5 minutes"});
            intervalMap.put("/repeat20min", new Object[]{1200L, "20 minutes"});
            intervalMap.put("/repeat60min", new Object[]{3600L, "1 hour"});
            intervalMap.put("/repeat120min", new Object[]{7200L, "2 hours"});
            intervalMap.put("/repeat24hour", new Object[]{86400L, "24 hours"});

            if (!intervalMap.containsKey(cmd)) {
                try {
                    sendMessage(chatId, "Invalid command.\nAvailable: " + String.join(", ", intervalMap.keySet()), null, messageId, null);
                    System.out.println("Sent invalid command message");
                } catch (IOException e) {
                    e.printStackTrace();
                }
                return "OK";
            }

            long interval = ((Object[]) intervalMap.get(cmd))[0] instanceof Long ? (Long) ((Object[]) intervalMap.get(cmd))[0] : 0;
            String display = (String) ((Object[]) intervalMap.get(cmd))[1];

            List<Long> albumIds = new ArrayList<>();
            boolean isAlbum = false;
            boolean isMedia = false;
            String originalText = (replied.has("text") ? replied.get("text").getAsString() : "") + (replied.has("caption") ? replied.get("caption").getAsString() : "");

            if (replied.has("media_group_id")) {
                String mgid = replied.get("media_group_id").getAsString();
                String key = chatId + "_" + mgid;
                long waited = 0;
                double maxWait = 4.5;
                double step = 0.35;
                while (waited < maxWait) {
                    if (mediaGroups.containsKey(key) && ((List<Long>) mediaGroups.get(key).get("ids")).size() > 1) {
                        break;
                    }
                    try {
                        Thread.sleep((long) (step * 1000));
                    } catch (InterruptedException e) {
                        e.printStackTrace();
                    }
                    waited += step;
                    step = Math.min(step + 0.15, 0.8);
                }

                if (mediaGroups.containsKey(key)) {
                    albumIds = new ArrayList<>((List<Long>) mediaGroups.get(key).get("ids"));
                    Collections.sort(albumIds);
                } else {
                    albumIds.add(replied.get("message_id").getAsLong());
                }

                System.out.println("[ALBUM DETECT] chat=" + chatId + " | mgid=" + mgid + " | items=" + albumIds.size());

                if (albumIds.size() > 1) {
                    isAlbum = true;
                    String resultText = "**✓ Album detected** (" + albumIds.size() + " items)\nWill repeat every " + display + ".";
                    try {
                        sendMessage(chatId, resultText, "Markdown", messageId, null);
                    } catch (IOException e) {
                        e.printStackTrace();
                    }
                } else {
                    String resultText = "**⚠️ Only single message detected**\n" +
                            "If this was supposed to be an album,\n" +
                            "please use /stop send album again and try the repeat command again.";
                    try {
                        sendMessage(chatId, resultText, "Markdown", messageId, null);
                    } catch (IOException e) {
                        e.printStackTrace();
                    }
                }
                isMedia = true;
            } else {
                albumIds.add(replied.get("message_id").getAsLong());
                String[] mediaKeys = {"photo", "video", "animation", "audio", "voice", "document", "video_note", "sticker"};
                for (String key : mediaKeys) {
                    if (replied.has(key)) {
                        isMedia = true;
                        break;
                    }
                }
                String resultText = "**✓ Repeating started**\nInterval: every " + display;
                try {
                    sendMessage(chatId, resultText, "Markdown", messageId, null);
                    System.out.println("Sent repeating started message");
                } catch (IOException e) {
                    System.out.println("Failed to send repeating started: " + e.getMessage());
                    e.printStackTrace();
                }
            }

            Map<String, Object> jobRef = new HashMap<>();
            jobRef.put("message_ids", albumIds);
            jobRef.put("running", true);
            jobRef.put("interval", interval);
            jobRef.put("is_album", isAlbum);
            jobRef.put("is_media", isMedia);
            jobRef.put("original_text", originalText);

            final long finalChatId = chatId;
            final List<Long> finalAlbumIds = albumIds;
            final long finalInterval = interval;
            final boolean finalIsAlbum = isAlbum;
            final Map<String, Object> finalJobRef = jobRef;

            repeatJobs.computeIfAbsent(chatId, k -> new ArrayList<>()).add(jobRef);
            new Thread(() -> repeater(finalChatId, finalAlbumIds, finalInterval, finalJobRef, finalIsAlbum)).start();

            System.out.println("Repeater thread started for chat " + chatId + " interval=" + interval);

            return "OK";
        }

        // /verify fallback
        else if (text.trim().equals("/verify") && !String.valueOf(chatId).startsWith("-")) {
            doVerification(userId, chatId);
            return "OK";
        }

        // /stop
        else if (text.startsWith("/stop")) {
            if (!isAdmin) {
                try {
                    sendMessage(chatId, "Only group admins can stop repeating.", null, messageId, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
                return "OK";
            }

            if (repeatJobs.containsKey(chatId) && !repeatJobs.get(chatId).isEmpty()) {
                for (Map<String, Object> job : repeatJobs.get(chatId)) {
                    job.put("running", false);
                }
                repeatJobs.put(chatId, new ArrayList<>());
                try {
                    sendMessage(chatId, "🛑 All repeating tasks stopped", null, messageId, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
            } else {
                try {
                    sendMessage(chatId, "No active repeating tasks found.", null, messageId, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }
            return "OK";
        }

        System.out.println("No matching handler for this update");
        return "OK";
    }

    // -------------------- Repeater -------------------- //
    private static void repeater(long chatId, List<Long> messageIds, long interval, Map<String, Object> jobRef, boolean isAlbum) {
        List<Long> lastContentIds = new ArrayList<>();
        Long lastPromptId = null;

        String verificationPromptText = "🚨User !\n" +
                "Please verify yourself to gain full access.\n" +
                "Click the button to start verification";

        JsonObject verifyKeyboard = new JsonObject();
        JsonArray inlineKeyboard = new JsonArray();
        JsonArray row = new JsonArray();
        JsonObject button = new JsonObject();
        button.addProperty("text", "✅Click To Get Full Access");
        button.addProperty("url", "https://t.me/" + getBotUsername() + "?start=verify_" + chatId);
        row.add(button);
        inlineKeyboard.add(row);
        verifyKeyboard.add("inline_keyboard", inlineKeyboard);

        while ((boolean) jobRef.get("running")) {
            System.out.println("Repeater loop | chatId=" + chatId + " | interval=" + interval + "s");

            // Delete previous content + previous prompt (if was media)
            for (long mid : lastContentIds) {
                deleteMessage(chatId, mid);
            }
            if (lastPromptId != null) {
                deleteMessage(chatId, lastPromptId);
            }

            lastContentIds.clear();
            lastPromptId = null;

            if ((boolean) jobRef.get("is_media")) {
                try {
                    JsonObject payload = new JsonObject();
                    payload.addProperty("chat_id", chatId);
                    payload.addProperty("from_chat_id", chatId);
                    JsonArray idsArray = new JsonArray();
                    for (long id : messageIds) idsArray.add(id);
                    payload.add("message_ids", idsArray);
                    payload.addProperty("disable_notification", true);
                    RequestBody body = RequestBody.create(gson.toJson(payload), MediaType.get("application/json"));
                    Request request = new Request.Builder().url(BOT_API + "/copyMessages").post(body).build();
                    Response response = client.newCall(request).execute();
                    if (response.code() == 200 && gson.fromJson(response.body().string(), JsonObject.class).get("ok").getAsBoolean()) {
                        JsonElement result = gson.fromJson(response.body().string(), JsonObject.class).get("result");
                        if (result.isJsonArray()) {
                            for (JsonElement m : result.getAsJsonArray()) {
                                lastContentIds.add(m.getAsJsonObject().get("message_id").getAsLong());
                            }
                        } else {
                            lastContentIds.add(result.getAsJsonObject().get("message_id").getAsLong());
                        }
                        System.out.println("Copied media message(s) in " + chatId);
                    } else {
                        System.out.println("copyMessages failed: " + response.code() + " " + response.body().string());
                    }

                    // Send small verification message below media
                    Response promptResp = sendMessage(chatId, verificationPromptText, null, null, verifyKeyboard);
                    if (promptResp.code() == 200 && gson.fromJson(promptResp.body().string(), JsonObject.class).get("ok").getAsBoolean()) {
                        lastPromptId = gson.fromJson(promptResp.body().string(), JsonObject.class).getAsJsonObject("result").get("message_id").getAsLong();
                        System.out.println("Sent verification prompt in " + chatId);
                    }
                } catch (IOException e) {
                    System.out.println("Media repeat failed: " + e.getMessage());
                    e.printStackTrace();
                }
            } else {
                // Text / link → re-send with inline button DIRECTLY attached
                String textToRepeat = (String) jobRef.getOrDefault("original_text", "Repeated message");
                String parseMode = textToRepeat.contains("<") ? "HTML" : null;
                try {
                    Response resp = sendMessage(chatId, textToRepeat, parseMode, null, verifyKeyboard);
                    if (resp.code() == 200 && gson.fromJson(resp.body().string(), JsonObject.class).get("ok").getAsBoolean()) {
                        lastContentIds.add(gson.fromJson(resp.body().string(), JsonObject.class).getAsJsonObject("result").get("message_id").getAsLong());
                        System.out.println("Sent text repeat in " + chatId);
                    } else {
                        System.out.println("sendMessage failed for text repeat: " + resp.code());
                    }
                } catch (IOException e) {
                    System.out.println("Text repeat failed: " + e.getMessage());
                    e.printStackTrace();
                }
            }

            try {
                Thread.sleep(interval * 1000);
            } catch (InterruptedException e) {
                System.out.println("Repeater sleep interrupted: " + e.getMessage());
                e.printStackTrace();
            }
        }
        System.out.println("Repeater stopped for chat " + chatId);
    }

    // ... keepAlive and getMe unchanged ...
}
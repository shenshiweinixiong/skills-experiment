package com.horsecoder.common.whuTalent.core.flow.Run.code;

import cc.eamon.open.flow.core.FlowEngine;
import cc.eamon.open.flow.core.stereotype.Flow;
import cc.eamon.open.flow.spring.FlowComponent;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * Scoped OfficeBench transport: Spring invokes the local deterministic bridge.
 * The bridge executes the selected case; this is not native Java skill execution.
 */
@FlowComponent
public class FlowCodeRun {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final int MAX_REQUEST_BYTES = 256 * 1024;
    private static final int MAX_RESPONSE_BYTES = 1024 * 1024;
    private static final Set<String> CASE_IDS = set(
            "1-3/0", "1-3/1", "1-3/2", "1-3/3", "1-4/0", "1-4/1",
            "1-4/2", "1-4/3", "1-5/0", "1-5/1", "1-5/2", "1-6/1",
            "1-6/2", "1-6/4", "1-9/2", "1-11/0", "1-11/1",
            "1-12/0", "1-13/2", "1-18/1", "1-23/0");
    private static final Set<String> NODE_IDS = set(
            "locate", "classify", "files", "sheets", "path_guard",
            "semantic_guard", "native_guard", "commit");
    private static final Set<String> EDGES = set(
            "locate|classify|serial", "classify|files|condition",
            "classify|sheets|condition", "files|path_guard|serial",
            "sheets|path_guard|serial", "path_guard|semantic_guard|parallel-readonly",
            "path_guard|native_guard|parallel-readonly", "semantic_guard|commit|join-all",
            "native_guard|commit|join-all");
    private static final Set<String> ELEMENT_FIELDS = set(
            "id", "name", "type", "color", "x", "y", "select", "locked", "skill");
    private static final Set<String> LINK_FIELDS = set(
            "id", "name", "type", "color", "points", "fromElementId", "toElementId");
    private static final Set<String> SKILLS = set(
            "locate|officebench.locate", "classify|officebench.intent", "files|officebench.file-action",
            "sheets|officebench.sheet-action", "path_guard|officebench.output-path-guard",
            "semantic_guard|officebench.semantic-guard", "native_guard|officebench.native-score",
            "commit|officebench.commit");

    /** Preserve the teacher flow contract: structure in, String result out. */
    @Flow("FLOW_CODE_RUN")
    public void flowCodeRun(String structure) {
        String result = runLocalBridge(structure);
        FlowEngine.instance().register("result", result);
    }

    static String runLocalBridge(String structure) {
        try {
            if (structure == null || structure.getBytes(StandardCharsets.UTF_8).length > MAX_REQUEST_BYTES) {
                throw new IllegalArgumentException("invalid structure size");
            }
            JsonNode request = JSON.readTree(structure);
            String caseId = validateRequest(request);
            byte[] payload = JSON.writeValueAsBytes(request);
            if (payload.length > MAX_REQUEST_BYTES) {
                throw new IllegalArgumentException("invalid structure size");
            }
            int port = bridgePort();
            // Fixed numeric loopback destination; structure never supplies a URL, path, or command.
            HttpURLConnection connection = (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/run").openConnection();
            try {
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(3000);
                connection.setReadTimeout(120000);
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setRequestProperty("Accept", "application/json");
                connection.setFixedLengthStreamingMode(payload.length);
                connection.setDoOutput(true);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(payload);
                }
                if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) {
                    throw new IOException("local OfficeBench bridge returned HTTP " + connection.getResponseCode());
                }
                String response;
                try (InputStream input = connection.getInputStream()) {
                    response = new String(readBounded(input), StandardCharsets.UTF_8);
                }
                JsonNode parsed = JSON.readTree(response);
                if (parsed == null || !parsed.isObject() || !caseId.equals(text(parsed, "case_id"))
                        || !parsed.hasNonNull("execution") || !parsed.path("result").isObject()
                        || !parsed.path("result").hasNonNull("status")) {
                    throw new IOException("invalid local OfficeBench bridge response");
                }
                return response;
            } finally {
                connection.disconnect();
            }
        } catch (IOException exception) {
            throw new IllegalStateException("local OfficeBench bridge unavailable or returned an invalid result", exception);
        }
    }

    static String validateRequest(JsonNode request) {
        if (!fieldsExactly(request, set("case_id", "graph"))) {
            throw new IllegalArgumentException("structure requires only case_id and graph");
        }
        String caseId = text(request, "case_id");
        if (!CASE_IDS.contains(caseId)) {
            throw new IllegalArgumentException("unknown OfficeBench case");
        }
        JsonNode graph = request.path("graph");
        if (!fieldsExactly(graph, set("id", "elements", "links")) || !shortText(graph, "id", 100)) {
            throw new IllegalArgumentException("graph must contain id, elements, and links");
        }
        JsonNode elements = graph.path("elements");
        JsonNode links = graph.path("links");
        if (!elements.isArray() || elements.size() != NODE_IDS.size() || !links.isArray() || links.size() != EDGES.size()) {
            throw new IllegalArgumentException("graph differs from frozen node/edge counts");
        }
        Set<String> nodeIds = new HashSet<>();
        for (JsonNode element : elements) {
            String id = text(element, "id");
            if (!fieldsWithin(element, ELEMENT_FIELDS) || !NODE_IDS.contains(id) || !nodeIds.add(id)
                    || !"model".equals(text(element, "type")) || !shortText(element, "name", 120)
                    || !coordinate(element.path("x")) || !coordinate(element.path("y"))) {
                throw new IllegalArgumentException("invalid frozen graph element");
            }
            JsonNode skill = element.get("skill");
            if (skill != null && (!skill.isTextual() || !SKILLS.contains(id + "|" + skill.asText()))) {
                // The bridge independently checks skills against its frozen structure.
                throw new IllegalArgumentException("graph element skill differs from frozen structure");
            }
        }
        if (!NODE_IDS.equals(nodeIds)) {
            throw new IllegalArgumentException("graph node ids differ from frozen structure");
        }
        Set<String> edgeKeys = new HashSet<>();
        Set<String> linkIds = new HashSet<>();
        for (JsonNode link : links) {
            String id = text(link, "id");
            String key = text(link, "fromElementId") + "|" + text(link, "toElementId") + "|" + text(link, "name");
            if (!fieldsWithin(link, LINK_FIELDS) || id == null || id.length() > 100 || !linkIds.add(id)
                    || !"relation".equals(text(link, "type")) || !EDGES.contains(key) || !edgeKeys.add(key)) {
                throw new IllegalArgumentException("invalid frozen graph link");
            }
            JsonNode points = link.path("points");
            if (!points.isArray() || points.size() > 128) {
                throw new IllegalArgumentException("invalid link points");
            }
            for (JsonNode point : points) {
                if (!fieldsExactly(point, set("x", "y")) || !coordinate(point.path("x")) || !coordinate(point.path("y"))) {
                    throw new IllegalArgumentException("invalid link point");
                }
            }
        }
        return caseId;
    }

    private static int bridgePort() {
        String configured = System.getProperty("officebench.bridge.port", "8765");
        if (!configured.matches("[0-9]{1,5}")) {
            throw new IllegalArgumentException("invalid OfficeBench bridge port");
        }
        int port = Integer.parseInt(configured);
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("invalid OfficeBench bridge port");
        }
        return port;
    }

    private static byte[] readBounded(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (output.size() + count > MAX_RESPONSE_BYTES) {
                throw new IOException("local OfficeBench bridge response too large");
            }
            output.write(buffer, 0, count);
        }
        return output.toByteArray();
    }

    private static boolean fieldsExactly(JsonNode object, Set<String> expected) {
        if (object == null || !object.isObject() || object.size() != expected.size()) {
            return false;
        }
        for (String name : expected) {
            if (!object.has(name)) {
                return false;
            }
        }
        return true;
    }

    private static boolean fieldsWithin(JsonNode object, Set<String> allowed) {
        if (!object.isObject()) {
            return false;
        }
        java.util.Iterator<String> names = object.fieldNames();
        while (names.hasNext()) {
            if (!allowed.contains(names.next())) {
                return false;
            }
        }
        return true;
    }

    private static boolean shortText(JsonNode node, String field, int maximum) {
        String value = text(node, field);
        return value != null && value.length() <= maximum;
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isTextual() ? value.asText() : null;
    }

    private static boolean coordinate(JsonNode value) {
        return value.isNumber() && Double.isFinite(value.asDouble()) && Math.abs(value.asDouble()) <= 100000;
    }

    private static Set<String> set(String... values) {
        return new HashSet<>(Arrays.asList(values));
    }
}

package com.horsecoder.common.whuTalent.core.flow.Run.code;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

public class FlowCodeRunTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String[] NODES = {
            "locate", "classify", "files", "sheets", "path_guard", "semantic_guard", "native_guard", "commit"
    };
    private static final String[][] EDGES = {
            {"locate", "classify", "serial"}, {"classify", "files", "condition"},
            {"classify", "sheets", "condition"}, {"files", "path_guard", "serial"},
            {"sheets", "path_guard", "serial"}, {"path_guard", "semantic_guard", "parallel-readonly"},
            {"path_guard", "native_guard", "parallel-readonly"}, {"semantic_guard", "commit", "join-all"},
            {"native_guard", "commit", "join-all"}
    };

    private ObjectNode request() {
        ObjectNode request = JSON.createObjectNode();
        request.put("case_id", "1-4/3");
        ObjectNode graph = request.putObject("graph");
        graph.put("id", "officebench-week4");
        ArrayNode elements = graph.putArray("elements");
        for (String id : NODES) {
            ObjectNode element = elements.addObject();
            element.put("id", id);
            element.put("type", "model");
            element.put("name", id);
            element.put("x", 10);
            element.put("y", 20);
        }
        ArrayNode links = graph.putArray("links");
        for (String[] edge : EDGES) {
            ObjectNode link = links.addObject();
            link.put("id", edge[0] + "-" + edge[1]);
            link.put("type", "relation");
            link.put("fromElementId", edge[0]);
            link.put("toElementId", edge[1]);
            link.put("name", edge[2]);
            link.putArray("points");
        }
        return request;
    }

    @Test
    public void acceptsFrozenViewAndSelectedCase() {
        assertEquals("1-4/3", FlowCodeRun.validateRequest(request()));
    }

    @Test
    public void rejectsUnlistedCaseAndExtraExecutionFields() {
        ObjectNode badCase = request();
        badCase.put("case_id", "../../etc/passwd");
        rejects(badCase);
        ObjectNode command = request();
        command.put("command", "whoami");
        rejects(command);
        ObjectNode address = request();
        address.put("url", "http://example.com");
        rejects(address);
    }

    @Test
    public void rejectsMutatedGraphAndDuplicateNodes() {
        ObjectNode missing = request();
        ((ArrayNode) missing.path("graph").path("links")).remove(0);
        rejects(missing);
        ObjectNode duplicate = request();
        ((ObjectNode) duplicate.path("graph").path("elements").get(1)).put("id", "locate");
        rejects(duplicate);
        ObjectNode mutated = request();
        ((ObjectNode) mutated.path("graph").path("elements").get(1)).put("skill", "shell.exec");
        rejects(mutated);
        ObjectNode extra = request();
        ((ObjectNode) extra.path("graph").path("links").get(0)).put("command", "whoami");
        rejects(extra);
    }

    @Test
    public void rejectsInvalidStructureBeforeNetwork() {
        try {
            FlowCodeRun.runLocalBridge("{not json");
            fail("invalid JSON accepted");
        } catch (IllegalStateException expected) {
            // Invalid JSON cannot reach the bridge.
        }
    }

    private void rejects(JsonNode request) {
        try {
            FlowCodeRun.validateRequest(request);
            fail("invalid request accepted");
        } catch (IllegalArgumentException expected) {
            // Validation must fail before any outbound request.
        }
    }
}

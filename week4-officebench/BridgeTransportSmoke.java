package com.horsecoder.common.whuTalent.core.flow.Run.code;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

public class BridgeTransportSmoke {
    public static void main(String[] args) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        ObjectNode request = mapper.createObjectNode();
        request.put("case_id", "1-4/3");
        ObjectNode graph = request.putObject("graph");
        graph.put("id", "week4-transport-smoke");
        String[] ids = {"locate", "classify", "files", "sheets", "path_guard", "semantic_guard", "native_guard", "commit"};
        String[] skillIds = {"officebench.locate", "officebench.intent", "officebench.file-action", "officebench.sheet-action", "officebench.output-path-guard", "officebench.semantic-guard", "officebench.native-score", "officebench.commit"};
        ArrayNode nodes = graph.putArray("elements");
        for (int i = 0; i < ids.length; i++) {
            ObjectNode node = nodes.addObject();
            node.put("id", ids[i]); node.put("name", ids[i]); node.put("type", "model");
            node.put("skill", skillIds[i]); node.put("x", 20 + i * 100); node.put("y", 150);
        }
        String[][] edges = {{"locate", "classify", "serial"}, {"classify", "files", "condition"}, {"classify", "sheets", "condition"}, {"files", "path_guard", "serial"}, {"sheets", "path_guard", "serial"}, {"path_guard", "semantic_guard", "parallel-readonly"}, {"path_guard", "native_guard", "parallel-readonly"}, {"semantic_guard", "commit", "join-all"}, {"native_guard", "commit", "join-all"}};
        ArrayNode links = graph.putArray("links");
        for (int i = 0; i < edges.length; i++) {
            ObjectNode link = links.addObject();
            link.put("id", "e" + i); link.put("name", edges[i][2]); link.put("type", "relation");
            link.put("fromElementId", edges[i][0]); link.put("toElementId", edges[i][1]); link.putArray("points");
        }
        String result = FlowCodeRun.runLocalBridge(mapper.writeValueAsString(request));
        if (!"passed".equals(mapper.readTree(result).path("result").path("status").asText())) {
            throw new AssertionError("bridge result not passed");
        }
        System.out.println("Spring flow transport to local bridge: passed");
    }
}

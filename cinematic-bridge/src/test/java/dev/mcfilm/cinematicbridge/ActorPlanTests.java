package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.json.MiniJson;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Pure Java contract validation for the constrained Carpet actor plan. */
public final class ActorPlanTests {
    private static int passed;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        Path valid = Path.of("contracts/v3/fixtures/actor/valid-walk-look.json");
        Path invalid = Path.of("contracts/v3/fixtures/actor/invalid-free-command.json");
        Map<String, Object> plan = asMap(MiniJson.parse(Files.readString(valid)));
        check("valid fixture parses", ActorPlan.parse(plan).actors().size() == 1);
        Map<String, Object> withCommand = asMap(MiniJson.parse(Files.readString(invalid)));
        expectReject("free-form command rejected", withCommand);

        Map<String, Object> outside = deepCopy(plan);
        Map<String, Object> actor = asMap(((List<?>) outside.get("actors")).getFirst());
        Map<String, Object> step = asMap(((List<?>) actor.get("steps")).get(1));
        step.put("target", Map.of("x", 99L, "y", -60L, "z", 1.5));
        expectReject("outside work region rejected", outside);

        Map<String, Object> unknownAction = deepCopy(plan);
        actor = asMap(((List<?>) unknownAction.get("actors")).getFirst());
        step = asMap(((List<?>) actor.get("steps")).get(1));
        step.put("action", "shell");
        expectReject("unknown action rejected", unknownAction);

        Map<String, Object> nonFinite = deepCopy(plan);
        actor = asMap(((List<?>) nonFinite.get("actors")).getFirst());
        actor.put("yaw", Double.NaN);
        expectReject("non-finite rotation rejected", nonFinite);

        Map<String,Object> recoil=deepCopy(plan);
        actor=asMap(((List<?>)recoil.get("actors")).getFirst());
        step=asMap(((List<?>)actor.get("steps")).get(1)); step.put("action","recoil_to");
        check("bounded recoil accepted",ActorPlan.parse(recoil).actors().size()==1);
        step.put("target",Map.of("x",5.5,"y",-60.0,"z",1.5)); expectReject("long recoil rejected",recoil);
        Map<String,Object> drop=deepCopy(plan);
        actor=asMap(((List<?>)drop.get("actors")).getFirst());step=asMap(((List<?>)actor.get("steps")).getFirst());
        step.put("action","drop_material");step.put("target",Map.of("x",1.5,"y",-54.0,"z",1.5));
        check("bounded material drop accepted",ActorPlan.parse(drop).actors().size()==1);
        step.put("target",Map.of("x",1.5,"y",-59.0,"z",1.5));expectReject("low material drop rejected",drop);
        Map<String,Object> visual=deepCopy(plan);actor=asMap(((List<?>)visual.get("actors")).getFirst());
        actor.put("skin_ref","classmate:zhou");step=asMap(((List<?>)actor.get("steps")).getFirst());step.put("action","phone");
        check("registered visual phone pose accepted",ActorPlan.parse(visual).actors().size()==1);
        actor.put("skin_ref",null);expectReject("phone without model rejected",visual);
        actor.put("skin_ref","C:/arbitrary.png");expectReject("arbitrary appearance path rejected",visual);
        Map<String,Object> board=deepCopy(plan);actor=asMap(((List<?>)board.get("actors")).getFirst());
        actor.put("steps",List.of(new LinkedHashMap<>(Map.of("start_tick",0,"duration_ticks",50,"action","prepare_board","target",Map.of("x",1.5,"y",-54.0,"z",1.5))),new LinkedHashMap<>(Map.of("start_tick",50,"duration_ticks",50,"action","drop_board"))));
        check("prepared board release accepted",ActorPlan.parse(board).actors().size()==1);
        step=asMap(((List<?>)actor.get("steps")).getFirst());step.put("target",Map.of("x",1.5,"y",-54.0,"z",7.5));expectReject("board footprint escapes region rejected",board);
        actor.put("steps",List.of(Map.of("start_tick",0,"duration_ticks",100,"action","drop_board")));expectReject("unprepared board release rejected",board);
        actor.put("steps",List.of(Map.of("start_tick",0,"duration_ticks",100,"action","prepare_board","target",Map.of("x",1.5,"y",-54.0,"z",1.5))));expectReject("unreleased board rejected",board);
        Map<String,Object> groceries=asMap(MiniJson.parse(Files.readString(Path.of("contracts/v3/fixtures/actor/valid-grocery-pickup.json"))));
        check("owned grocery pair accepted",ActorPlan.parse(groceries).actors().size()==2);
        Map<String,Object> ordinaryLong=deepCopy(plan);ordinaryLong.put("duration_ticks",1201);
        for(Object raw:(List<?>)ordinaryLong.get("actors"))asMap(raw).put("steps",List.of(Map.of("start_tick",0,"duration_ticks",1201,"action","idle")));
        expectReject("ordinary take cannot use grocery duration extension",ordinaryLong);
        Map<String,Object> badGroceries=deepCopy(groceries);badGroceries.put("actors",List.of(((List<?>)badGroceries.get("actors")).getFirst()));expectReject("uncollected groceries rejected",badGroceries);
        badGroceries=deepCopy(groceries);actor=asMap(((List<?>)badGroceries.get("actors")).get(1));actor.put("skin_ref","classmate:a");expectReject("unregistered grocery collector rejected",badGroceries);
        badGroceries=deepCopy(groceries);actor=asMap(((List<?>)badGroceries.get("actors")).get(1));actor.put("start",Map.of("x",5.0,"y",-60.0,"z",1.5));expectReject("out of reach grocery pickup rejected",badGroceries);
        badGroceries=deepCopy(groceries);actor=asMap(((List<?>)badGroceries.get("actors")).get(1));step=asMap(((List<?>)actor.get("steps")).get(1));step.put("target",Map.of("x",2.0,"y",-60.0,"z",1.5));expectReject("different grocery target rejected",badGroceries);
        badGroceries=deepCopy(groceries);actor=asMap(((List<?>)badGroceries.get("actors")).get(1));asMap(((List<?>)actor.get("steps")).getFirst()).put("duration_ticks",10);step=asMap(((List<?>)actor.get("steps")).get(1));step.put("start_tick",10);step.put("duration_ticks",90);expectReject("pickup before scatter settled rejected",badGroceries);
        Map<String,Object> call=deepCopy(plan);actor=asMap(((List<?>)call.get("actors")).getFirst());
        actor.put("skin_ref","classmate:chen");actor.put("steps",List.of(Map.of("start_tick",0,"duration_ticks",100,"action","phone_call_sit")));
        check("seated phone call accepted",ActorPlan.parse(call).actors().size()==1);
        actor.put("skin_ref","classmate:teacher");expectReject("phone call without phone-bearing role rejected",call);
        actor.put("skin_ref",null);expectReject("phone call without registered model rejected",call);
        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(System.out::println);
        if (!failures.isEmpty()) System.exit(1);
    }

    @SuppressWarnings("unchecked") private static Map<String, Object> asMap(Object value) { return (Map<String, Object>) value; }
    private static Map<String, Object> deepCopy(Map<String, Object> value) { return asMap(MiniJson.parse(MiniJson.write(value))); }
    private static void expectReject(String name, Map<String, Object> value) {
        try { ActorPlan.parse(value); failures.add("FAIL " + name + " was accepted"); }
        catch (IllegalArgumentException expected) { check(name, true); }
    }
    private static void check(String name, boolean okay) { if (okay) passed++; else failures.add("FAIL " + name); }
}

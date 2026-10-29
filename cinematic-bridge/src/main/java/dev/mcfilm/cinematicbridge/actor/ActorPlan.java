package dev.mcfilm.cinematicbridge.actor;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Pure, fail-closed actor plan parser. No command or code strings are representable. */
public record ActorPlan(String runId, String takeId, String world, String dimension,
                        Region region, int durationTicks, List<Actor> actors) {
    public record Point(double x, double y, double z) {
        public double distanceXZ(Point other) {
            return Math.hypot(x - other.x, z - other.z);
        }
    }
    public record Region(Point min, Point max) {
        public boolean contains(Point p) {
            return p.x >= min.x && p.x <= max.x && p.y >= min.y && p.y <= max.y
                && p.z >= min.z && p.z <= max.z;
        }
    }
    public record Step(int startTick, int durationTicks, String action,
                       Point target, int timeoutTicks, String itemRef, String actorRef) { }
    public record Actor(String actorId, String playerName, Point start, float yaw,
                        float pitch, String skinRef, List<Step> steps, List<Integer> mouthFrames) { }

    public static ActorPlan parse(Map<String, Object> input) {
        only(input, Set.of("schema_version", "run_id", "take_id", "world", "dimension",
            "build_region", "duration_ticks", "actors"), "plan");
        if (integer(input.get("schema_version"), "schema_version") != 1) bad("schema_version must be 1");
        String run = text(input.get("run_id"), "run_id");
        String take = text(input.get("take_id"), "take_id");
        String world = text(input.get("world"), "world");
        String dimension = text(input.get("dimension"), "dimension");
        if (!run.matches("[A-Za-z0-9_.-]{1,80}") || !take.matches("[A-Za-z0-9_.-]{1,80}")) bad("invalid run_id or take_id");
        if (!dimension.equals("minecraft:overworld")) bad("only the overworld is supported by actor plans");
        Map<String, Object> r = object(input.get("build_region"), "build_region");
        only(r, Set.of("min", "max"), "build_region");
        Region region = new Region(point(r.get("min"), "build_region.min"), point(r.get("max"), "build_region.max"));
        if (region.min.x >= region.max.x || region.min.y >= region.max.y || region.min.z >= region.max.z) bad("build_region min must be below max");
        if (region.max.x - region.min.x > 64 || region.max.y - region.min.y > 64 || region.max.z - region.min.z > 64) bad("build_region exceeds 64 blocks on an axis");
        int duration = integer(input.get("duration_ticks"), "duration_ticks");
        if (duration < 40 || duration > 3600) bad("duration_ticks must be 40..3600; takes above1200 require owned grocery pickup");
        List<?> rawActors = array(input.get("actors"), "actors");
        if (rawActors.isEmpty() || rawActors.size() > 8) bad("actors must contain 1..8 entries");
        Set<String> ids = new HashSet<>(), names = new HashSet<>();
        List<Actor> actors = new ArrayList<>();
        Step groceriesScatter=null,groceriesPickup=null;
        for (Object raw : rawActors) {
            Map<String, Object> a = object(raw, "actor");
            only(a, Set.of("actor_id", "player_name", "start", "yaw", "pitch", "skin_ref", "steps", "mouth_frames"), "actor");
            String id = text(a.get("actor_id"), "actor_id"), name = text(a.get("player_name"), "player_name");
            if (!id.matches("[A-Za-z0-9_.-]{1,48}") || !name.matches("[A-Za-z0-9_]{1,16}")) bad("invalid actor_id or player_name");
            if (!ids.add(id) || !names.add(name)) bad("actor_id and player_name must be unique");
            Point start = point(a.get("start"), "actor.start"); requireInside(region, start);
            float yaw = (float) finiteNumber(a.get("yaw"), "yaw"), pitch = (float) finiteNumber(a.get("pitch"), "pitch");
            if (yaw < -360 || yaw > 360 || pitch < -90 || pitch > 90) bad("yaw/pitch out of bounds");
            String skin = a.get("skin_ref") == null ? null : text(a.get("skin_ref"), "skin_ref");
            if(skin!=null && !skin.matches("classmate:(a|zhou|teacher|chen|elder|filmer|safety)")) bad("unregistered actor appearance");
            List<?> rawSteps = array(a.get("steps"), "steps");
            if (rawSteps.isEmpty() || rawSteps.size() > 64) bad("steps must contain 1..64 entries");
            List<Step> steps = new ArrayList<>();
            int cursor = 0, drops = 0;
            boolean boardPrepared=false, boardDropped=false;
            Point cursorPosition = start;
            for (Object rawStep : rawSteps) {
                Map<String, Object> step = object(rawStep, "step");
                only(step, Set.of("start_tick", "duration_ticks", "action", "target", "timeout_ticks", "item_ref", "actor_ref"), "step");
                int at = integer(step.get("start_tick"), "step.start_tick");
                int len = integer(step.get("duration_ticks"), "step.duration_ticks");
                String action = text(step.get("action"), "step.action");
                if(skin==null && Set.of("phone","phone_sit","phone_call","phone_call_sit","sit","explain","reach","down","scatter_groceries","pickup_groceries").contains(action))bad("registered model required for character poses");
                if (at != cursor || len < 1 || len > 3600) bad("steps must be contiguous and have positive duration");
                if (!Set.of("idle", "walk_to", "look_at", "sneak", "hold_item", "recoil_to", "swing_arm", "fall_down", "stand_up", "drop_material", "prepare_board", "drop_board", "phone", "phone_sit", "phone_call", "phone_call_sit", "sit", "explain", "reach", "down", "scatter_groceries", "pickup_groceries", "support_actor", "rise_supported", "push_actor", "phone_stop", "phone_place_sit", "phone_putaway", "phone_putaway_sit", "pack_bag_sit", "pack_bag_stand", "pickup_coat", "hold_coat").contains(action)) bad("unknown actor action");
                String actorRef = step.get("actor_ref") == null ? null : text(step.get("actor_ref"), "actor_ref");
                if (Set.of("support_actor","push_actor").contains(action) != (actorRef != null)) bad("actor_ref is required only for contact actions");
                if (action.equals("phone_stop") && (!"classmate:filmer".equals(skin) || len<30 || len>60 || steps.isEmpty() || !steps.getLast().action().equals("phone"))) bad("phone stop requires filmer,30..60ticks and preceding standing phone action");
                if (action.equals("push_actor") && (!"classmate:chen".equals(skin)||len<6||len>20)) bad("push requires worker and6..20ticks");
                if (action.equals("support_actor") && (!("classmate:chen".equals(skin)||"classmate:safety".equals(skin)) || len<20)) bad("support requires registered worker/safety and at least20ticks");
                if (action.equals("rise_supported") && (!"classmate:elder".equals(skin) || len<40 || len>100)) bad("supported rise requires elder and40..100ticks");
                if(Set.of("phone_call","phone_call_sit").contains(action) && !Set.of("classmate:a","classmate:zhou","classmate:chen","classmate:filmer","classmate:safety").contains(skin))bad("phone calls require a registered phone-bearing role");
                Point target = step.containsKey("target") ? point(step.get("target"), "step.target") : null;
                if ((action.equals("walk_to") || action.equals("look_at") || action.equals("recoil_to") || action.equals("drop_material") || action.equals("prepare_board") || action.equals("scatter_groceries") || action.equals("pickup_groceries") || action.equals("phone_place_sit") || action.equals("pickup_coat")) != (target != null)) bad(action + " target requirement mismatch");
                if (target != null) requireInside(region, target);
                if(action.equals("phone_place_sit") && (!"classmate:chen".equals(skin)||len<40||len>80||steps.isEmpty()||!steps.getLast().action().equals("phone_call_sit")||steps.stream().anyMatch(s->s.action().equals("phone_place_sit"))||start.distanceXZ(target)>1||target.y()-start.y()<.7||target.y()-start.y()>1.3))bad("phone placement requires chen,40..80ticks and preceding seated call within seated reach");
                if(steps.stream().anyMatch(s->s.action().equals("phone_place_sit"))&&!action.equals("sit"))bad("only seated rest follows phone placement");

                if(action.equals("phone_putaway")||action.equals("phone_putaway_sit")){
                    String previous=action.endsWith("_sit")?"phone_sit":"phone";
                    if(!Set.of("classmate:a","classmate:zhou").contains(skin==null?"":skin)||len<30||len>60||steps.isEmpty()||!steps.getLast().action().equals(previous))bad("student put-away requires matching preceding phone pose and30..60ticks");
                }
                if(!steps.isEmpty()&&(steps.getLast().action().equals("phone_putaway")||steps.getLast().action().equals("phone_putaway_sit"))){
                    String rest=steps.getLast().action().endsWith("_sit")?"sit":"idle";
                    if(!action.equals(rest))bad("put-away must be followed by matching rest pose");
                }
                int timeout = step.containsKey("timeout_ticks") ? integer(step.get("timeout_ticks"), "step.timeout_ticks") : -1;
                if ((action.equals("walk_to") || action.equals("recoil_to")) && (timeout < 1 || timeout > 1200)) bad("walk_to requires timeout_ticks 1..1200");
                if (!action.equals("walk_to") && !action.equals("recoil_to") && timeout != -1) bad("timeout_ticks only applies to walk_to");
                if (action.equals("walk_to") && cursorPosition.distanceXZ(target) > 8) bad("walk_to distance exceeds 8 blocks");
                if (action.equals("recoil_to") && (cursorPosition.distanceXZ(target) > 2.5 || Math.abs(cursorPosition.y()-target.y())>0.001)) bad("recoil_to must stay on one floor within 2.5 blocks");
                if (action.equals("drop_material") && (target.y()-cursorPosition.y()<2 || target.y()-cursorPosition.y()>12)) bad("material drop height must be 2..12 blocks");
                if(action.equals("prepare_board")){
                    if(boardPrepared || target.y()-cursorPosition.y()<2 || target.y()-cursorPosition.y()>12)bad("one prepared board, 2..12 blocks above actor floor");
                    if(target.x()-.5<region.min().x() || target.x()+.5>region.max().x() || target.z()-1<region.min().z() || target.z()+1>region.max().z() || target.y()+.3>region.max().y())bad("entire board footprint must stay inside build_region");
                    boardPrepared=true;
                }
                if(action.equals("drop_board")){if(!boardPrepared || boardDropped)bad("drop_board requires one previously prepared board");boardDropped=true;}
                if(action.equals("scatter_groceries")){
                    if(!"classmate:elder".equals(skin)||groceriesScatter!=null||cursorPosition.distanceXZ(target)>.35||Math.abs(cursorPosition.y()-target.y())>.001)bad("one elder grocery scatter at the actor floor");
                    if(target.x()-2.2<region.min.x||target.x()+2.2>region.max.x||target.z()-1.3<region.min.z||target.z()+1.3>region.max.z||target.y()+2.1>region.max.y)bad("grocery footprint escapes region");
                    groceriesScatter=new Step(at,len,action,target,timeout,null,null);
                }
                if(action.equals("pickup_groceries")){
                    if(!"classmate:filmer".equals(skin)||groceriesPickup!=null||Math.abs(cursorPosition.x()-target.x())>.025||Math.abs(cursorPosition.z()-(target.z()-.4))>.025||Math.abs(cursorPosition.y()-target.y())>.001||!GroceryApproachRig.supportedDuration(len))bad("one filmer grocery pickup, 3040 legacy or1520 compact ticks at the initial center.x/center.z-.4 anchor");
                    groceriesPickup=new Step(at,len,action,target,timeout,null,null);
                    cursorPosition=new Point(target.x()-.8,target.y(),target.z()+.3);
                }
                if (action.equals("walk_to") || action.equals("recoil_to")) cursorPosition = target;
                String item = step.get("item_ref") == null ? null : text(step.get("item_ref"), "item_ref");
                if (action.equals("hold_item") != (item != null)) bad("item_ref only applies to hold_item and is required");
                if (item != null && !item.equals("minecraft:book")) bad("only the registered vanilla book prop is supported");
                if (action.equals("drop_material") && ++drops > 1) bad("one material drop per actor");
                steps.add(new Step(at, len, action, target, timeout, item, actorRef));
                cursor += len;
            }
            if(boardPrepared && !boardDropped)bad("prepared board must be released in this take");
            List<Step> coats=steps.stream().filter(s->s.action().equals("pickup_coat")).toList();
            if(!coats.isEmpty()||steps.stream().anyMatch(s->s.action().equals("hold_coat"))){
                if(coats.size()!=1||!"classmate:a".equals(skin))bad("one registered A coat pickup before holding required");
                Step coat=coats.getFirst();int index=steps.indexOf(coat);
                if(index==0||index==steps.size()-1||coat.durationTicks()<60||coat.durationTicks()>100||steps.subList(0,index).stream().anyMatch(s->!s.action().equals("phone"))||steps.subList(index+1,steps.size()).stream().anyMatch(s->!s.action().equals("hold_coat")))bad("coat pickup between standing phone and hold only");
                double angle=Math.toRadians(yaw),dx=coat.target().x()-start.x(),dz=coat.target().z()-start.z(),x=Math.cos(angle)*dx+Math.sin(angle)*dz,z=-Math.sin(angle)*dx+Math.cos(angle)*dz,y=coat.target().y()-start.y();
                if(y<.9||y>1.2||x<.2||x>.65||z<.25||z>.65||Math.sqrt(Math.pow(x-.375,2)+Math.pow(y-1.4375,2)+z*z)>.73)bad("coat collar outside bounded right-hand tabletop reach");
                if(start.x()-1<region.min.x()||start.x()+1>region.max.x()||start.z()-1<region.min.z()||start.z()+1>region.max.z()||start.y()+1.9>region.max.y())bad("coat footprint escapes region");
            }
            List<Step> standing=steps.stream().filter(s->s.action().equals("pack_bag_stand")).toList();
            if(!standing.isEmpty()){
                Step pack=standing.getFirst();int index=steps.indexOf(pack);
                if(standing.size()!=1||!"classmate:chen".equals(skin)||pack.durationTicks()!=StandingPackingMotion.DURATION||index==0||index==steps.size()-1||steps.stream().anyMatch(s->s!=pack&&!s.action().equals("idle")))bad("one160tick Chen standing packing action between idle rests only");
                if(start.x()-.9<region.min.x()||start.x()+.9>region.max.x()||start.z()-.9<region.min.z()||start.z()+.9>region.max.z()||start.y()+1.7>region.max.y())bad("standing packing footprint escapes work region");
            }
            List<Step> packing=steps.stream().filter(s->s.action().equals("pack_bag_sit")).toList();
            if(!packing.isEmpty()){
                int index=steps.indexOf(packing.getFirst());Step pack=packing.getFirst();
                if(packing.size()!=1||!Set.of("classmate:a","classmate:zhou").contains(skin==null?"":skin)||pack.durationTicks()<80||pack.durationTicks()>120||index==0||index==steps.size()-1||steps.stream().anyMatch(s->s!=pack&&!s.action().equals("sit")))bad("one80..120tick student packing action between seated rests only");
                if(start.x()-.9<region.min.x()||start.x()+.9>region.max.x()||start.z()-.9<region.min.z()||start.z()+.9>region.max.z()||start.y()+1.7>region.max.y())bad("packing footprint escapes work region");
            }
            if(!steps.isEmpty()&&(steps.getLast().action().equals("phone_putaway")||steps.getLast().action().equals("phone_putaway_sit")))bad("put-away requires following rest pose");
            if (cursor != duration) bad("each actor timeline must cover duration_ticks exactly");
            List<Integer> mouthFrames=new ArrayList<>();
            if(a.get("mouth_frames")!=null){
                if(skin==null)bad("mouth frames require registered model");
                List<?> frames=array(a.get("mouth_frames"),"mouth_frames");
                if(frames.size()!=duration)bad("mouth frames must cover every take tick exactly");
                for(Object frame:frames){int value=integer(frame,"mouth frame");if(value<0||value>2)bad("mouth frame outside0..2");mouthFrames.add(value);}
            }
            actors.add(new Actor(id, name, start, yaw, pitch, skin, List.copyOf(steps), List.copyOf(mouthFrames)));
        }
        if(duration>1200&&groceriesPickup==null)bad("takes over1200ticks require the registered owned grocery pickup");
        if((groceriesScatter==null)!=(groceriesPickup==null))bad("grocery scatter requires one later pickup");
        if(groceriesScatter!=null&&(groceriesPickup.startTick()<groceriesScatter.startTick()+18||groceriesPickup.target().distanceXZ(groceriesScatter.target())>.001||Math.abs(groceriesPickup.target().y()-groceriesScatter.target().y())>.001))bad("pickup must follow scatter at the same grocery center");
        for (Actor actor : actors) for (Step step : actor.steps()) {
            if(step.action().equals("push_actor")){
                Actor targetActor=actors.stream().filter(a->a.actorId().equals(step.actorRef())).findFirst().orElse(null);
                int end=step.startTick()+step.durationTicks();
                if(targetActor==null||targetActor==actor||!"classmate:elder".equals(targetActor.skinRef()))bad("push target must be another registered elder");
                boolean standing=targetActor.steps().stream().anyMatch(s->s.action().equals("idle")&&s.startTick()<=step.startTick()&&s.startTick()+s.durationTicks()>=end);
                boolean recoil=targetActor.steps().stream().anyMatch(s->s.action().equals("recoil_to")&&s.startTick()==end);
                if(!standing||!recoil)bad("push requires standing elder followed immediately by scripted recoil");
            }
            if (step.action().equals("support_actor")) {
                Actor targetActor=actors.stream().filter(a->a.actorId().equals(step.actorRef())).findFirst().orElse(null);
                if(targetActor==null || targetActor==actor || !"classmate:elder".equals(targetActor.skinRef())) bad("support target must be another registered elder in this take");
            }
            if(step.action().equals("rise_supported")) {
                boolean held=actors.stream().flatMap(a->a.steps().stream()).anyMatch(s->s.action().equals("support_actor") && actor.actorId().equals(s.actorRef()) && s.startTick()<=step.startTick() && s.startTick()+s.durationTicks()>=step.startTick()+step.durationTicks());
                if(!held)bad("supported rise requires support for its entire interval");
            }
        }
        return new ActorPlan(run, take, world, dimension, region, duration, List.copyOf(actors));
    }

    private static Point point(Object value, String name) {
        Map<String, Object> map = object(value, name);
        only(map, Set.of("x", "y", "z"), name);
        return new Point(finiteNumber(map.get("x"), name + ".x"), finiteNumber(map.get("y"), name + ".y"), finiteNumber(map.get("z"), name + ".z"));
    }
    private static void requireInside(Region r, Point p) { if (!r.contains(p)) bad("position outside build_region"); }
    private static double finiteNumber(Object v, String n) {
        if (!(v instanceof Number number)) return badNumber(n);
        double d = number.doubleValue();
        if (!Double.isFinite(d) || Math.abs(d) > 30_000_000) return badNumber(n);
        return d;
    }
    private static double badNumber(String n) { throw new IllegalArgumentException(n + " must be a finite number"); }
    private static int integer(Object v, String n) {
        if (!(v instanceof Number number) || !Double.isFinite(number.doubleValue()) || number.doubleValue() != number.longValue()) bad(n + " must be an integer");
        long result = ((Number) v).longValue();
        if (result < Integer.MIN_VALUE || result > Integer.MAX_VALUE) bad(n + " out of range");
        return (int) result;
    }
    private static String text(Object v, String n) { if (!(v instanceof String s) || s.isBlank()) bad(n + " must be non-empty text"); return (String) v; }
    @SuppressWarnings("unchecked") private static Map<String, Object> object(Object v, String n) { if (!(v instanceof Map<?, ?>)) bad(n + " must be an object"); return (Map<String, Object>) v; }
    private static List<?> array(Object v, String n) { if (!(v instanceof List<?> list)) bad(n + " must be an array"); return (List<?>) v; }
    private static void only(Map<String, Object> map, Set<String> allowed, String n) { for (String key : map.keySet()) if (!allowed.contains(key)) bad("unsupported " + n + " field: " + key); }
    private static void bad(String message) { throw new IllegalArgumentException(message); }
}

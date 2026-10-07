package dev.mcfilm.cinematicbridge.actor;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
/** Only the owned actor runner can opt a UUID into the film fallen pose. */
public final class FallenPoses {
 private static final Set<UUID> OWNED = ConcurrentHashMap.newKeySet();
 public static boolean contains(UUID id){return OWNED.contains(id);}
 public static void add(UUID id){OWNED.add(id);}
 public static void remove(UUID id){OWNED.remove(id);}
 private FallenPoses(){}
}

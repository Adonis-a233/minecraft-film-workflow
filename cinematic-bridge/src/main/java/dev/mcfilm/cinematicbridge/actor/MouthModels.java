package dev.mcfilm.cinematicbridge.actor;
/** Item model identifiers are versioned with the registered actor resource pack. */
public final class MouthModels {
 private MouthModels(){}
 public static int modelData(String role,int frame){
  if(frame<0||frame>2)throw new IllegalArgumentException("mouth frame outside0..2");
  int base=switch(role){case "a"->72000;case "zhou"->72100;case "teacher"->72200;case "chen"->72300;case "elder"->72400;case "filmer"->72500;case "safety"->72600;default->throw new IllegalArgumentException("unregistered mouth role");};
  return base+(frame==0?1:49+frame);
 }
}

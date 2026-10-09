# Example assets and credits

This file describes the non-code content. The root GPL license applies only to the project's own code; it does not relicense Minecraft, third-party mods, maps, character art, or the rendered film.

## City/campus map and world save

- assets/worlds/city-campus/CityCampus-world.zip is a project world snapshot based on Minecraft Java 1.21.1. It combines a city/town reference layout supplied for this production with the Northfield school schematic below.
- Northfield Copper Cupola Grammar School, by BuildSchem / Schemcraft: assets/sources/northfield/northfield-original.zip. Source page: https://schemcraft.com/schematics/northfield-copper-cupola-grammar-school. The source manifest identifies CC BY-NC 4.0. Attribution is retained; the project copy is a converted/placed Minecraft world version and is shared for non-commercial use. See https://creativecommons.org/licenses/by-nc/4.0/ .
- The town layout source was supplied by a project collaborator for this sample. The provided files did not include a separate public license; the creator retains rights. This repository does not claim ownership or apply the code license to those parts. Keep use non-commercial and ask the creator before adapting or redistributing the source independently.
- The distributed save omits player data, advancements, statistics, session locks, launcher data, local logs and user-specific configuration. It contains map/world data only.

## Characters

- assets/resourcepacks/characters-v8-1.21.1.zip, characters-v11-1.21.1.zip and characters-v12-1.21.1.zip are the pinned character-pack versions for different shots in the v10 draft. They reuse models and design supplied by a project collaborator and add project-specific adaptations. The original creator retains rights to their source design; no standalone open license was supplied with the files.
- These packs are shared for this non-commercial project demonstration. Do not treat them as GPL-licensed or as permission to reuse the collaborator's character designs outside the sample.
- The NicoRTX Japanese School resource pack is referenced by hash in the master recipe but is not redistributed here. For live re-rendering, obtain the compatible pack from its author and verify the SHA-256 listed in docs/FILM_MASTER.md.

## Video examples

- assets/videos/film-full-1080p-510s-subtitles-v10.mp4
- assets/videos/film-full-1080p-510s-clean-v10.mp4

Both are project-produced, 510-second, 1920×1080, 30 fps **drafts kept for workflow study**. The film needs substantial reconstruction and has not been accepted as a final creative deliverable. Full video/audio decode, constant-frame-rate and manifest-hash checks passed for these exact source files; those technical checks do not validate story, performance, visual quality, or sound. The recorded audit was scoped; it does not claim every frame was inspected or that normal-speed audio listening and user acceptance are complete. The draft renders Minecraft content and the separately credited character/map assets above. These clips are provided as non-commercial workflow examples, not relicensed by GPL.

The chapter clips under `assets/renders/`, pinned shot footage under `assets/footage/v10/`, graphics and subtitle files under `assets/graphics/v10/`, and the lossless soundtrack under `assets/audio/` are source components of those same two film examples. Eight replay masters under `assets/replays/v10/` are provided for the declared shots. Their manifests and JSON recipes preserve hashes and order. These components have the same non-commercial sample scope and third-party character/map credits as the draft films. Three older video inserts remain fixed because their resource-pack history is not sufficiently evidenced for live re-rendering.

## Export hygiene

The release includes two versioned v10 example videos, one sanitized city/campus world save, and the pinned footage, graphics, replay masters, and character packs required by the master recipe. Unrelated intermediate drafts, work logs, test databases and local-instance snapshots were excluded. Replay metadata was inspected for player identity fields and local paths before publication. The source Windows profile, launcher settings, player UUID folders, secrets and unrelated working files were excluded.

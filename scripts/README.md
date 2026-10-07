# Scripts

- bootstrap.ps1: install the locked Python development environment and run offline regression and CLI smoke checks. It does not launch Minecraft.
- prepare_superflat_save.py: create a new isolated creative superflat world from an explicit level.dat template. It validates the destination and refuses to overwrite existing saves. Read --help before using it.

Game launch, account/profile discovery and live-world writes are intentionally not part of bootstrap.

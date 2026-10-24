# SECURITY.md — Privacy and security model

The system transmits the owner's real desktop. The 20 mandatory safeguards from `PROJECT_SPEC.md` §8 are binding design
constraints for every component. This file will map each safeguard to the code that enforces it and to the tests that
prove it, once the architecture is chosen. Until then: no capture code exists, no endpoints exist, no secrets exist.

Rules already in force: secrets never committed (`.gitignore` excludes `*.env`, local configs, `secrets/`, captures);
captured frames are never written to the repository.

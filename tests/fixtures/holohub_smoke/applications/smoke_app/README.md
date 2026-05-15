# Smoke Test App

Minimal in-tree HoloHub-style application used by `holoscan-cli`'s
release-validation tests. Not a real Holoscan app — exists only so
`holoscan list` / `holoscan run <project> --dryrun` have a deterministic
project to discover when running against the installed wheel, without
needing an external HoloHub / Isaac OS / I4H checkout.

# Release manifests

`holoscan package` in holoscan-cli 2.9.0 through 4.2.0 downloads its artifact
manifest from this directory on the `main` branch at runtime:

- `releases/<cli-version>/artifacts.json`: all packages before 3.7.0, and CUDA 13 packages from 3.7.0
- `releases/<cli-version>/artifacts-cu12.json`: CUDA 12 packages from 3.7.0

The URL is hard-coded in those releases, so these files must stay on `main` at
these paths. Moving or deleting them makes `holoscan package` fail with
"Not Found" for existing installations unless `--source` is passed (issue #182).
Later CLI versions do not read these files.

# {{ cookiecutter.module_repo_name }} package

This directory defines the Debian package for `{{ cookiecutter.module_repo_name }}`.

## Usage

```bash
holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator DEB
```

## metadata.json

`metadata.json` registers this package with the holohub CLI. Two fields matter:

- **`package` key** — marks this directory as a HoloHub *package* project. The CLI
  discovers it via the recursive `HOLOSCAN_CLI_SEARCH_PATH` scan from the module root,
  which makes it appear under the `PACKAGES` section of `holoscan list`.
- **`package.dockerfile`** — declares a Dockerfile path (relative to the module
  root) for this package-project record. When packaging this generated module
  by name, `holoscan package` instead selects the root `module` record and its
  `module.dockerfile`.

## Holoscan SDK dependency

The generated Debian package selects the dependency matching the target
architecture and the CUDA 13 Holoscan SDK image selected by the project
`Dockerfile`:

- x86_64: `holoscan-cuda-13 (>= {{ cookiecutter.holoscan_version }}), holoscan-cuda-13 (<< 5.0)`
- aarch64 (Jetson Thor): `holoscan (>= {{ cookiecutter.holoscan_version }}), holoscan (<< 5.0)`

Holoscan SDK 4.x also supports CUDA 12 on compatible platforms. To target CUDA
12 on x86_64, change `HOLOSCAN_DEB_DEPENDENCY` in this directory's
`CMakeLists.txt` to `holoscan-cuda-12 (>= {{ cookiecutter.holoscan_version }}), holoscan-cuda-12 (<< 5.0)`
and select a matching CUDA 12 SDK image and CLI `--cuda 12` configuration. Keep
these settings aligned so package installation cannot select a different SDK
variant from the one used to build and test the module. Add any other runtime
Debian packages to the same semicolon-separated `DEPENDS` value passed to
`holohub_configure_deb()`.

Looking for Python packaging? Review the project [pyproject.toml](../../pyproject.toml)
for configuration.

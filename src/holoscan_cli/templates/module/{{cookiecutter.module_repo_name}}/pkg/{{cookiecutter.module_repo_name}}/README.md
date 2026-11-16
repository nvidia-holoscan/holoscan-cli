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

The package depends on `holoscan (>= {{ cookiecutter.holoscan_version }})`, the Debian alias of
`holoscan-cuda-13` on Holoscan SDK 5.0 platforms.
{%- if cookiecutter.__python_bindings == 'yes' %} The Python bindings ship separately as a wheel
(`holoscan package {{ cookiecutter.module_repo_name }} --pkg-generator WHEEL`).
{%- else %} Python wheel packaging returns in a later release.
{%- endif %}

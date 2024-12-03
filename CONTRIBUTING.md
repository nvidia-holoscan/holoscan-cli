# Contributing to Holoscan CLI

## Prerequisites

To contribute to the Holoscan CLI repository, you will need to install the following dependencies:

- [poetry](https://python-poetry.org/docs/#installation)

### Workflow

1. Developers must first [fork](https://help.github.com/en/articles/fork-a-repo) the [upstream](https://github.com/nvidia-holoscan/holoscan-cli) Holoscan CLI repository.

1. Git clone the forked repository and push changes to the personal fork.

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_FORK.git holoscan-cli
# Checkout the targeted branch and commit changes
# Push the commits to a branch on the fork (remote).
git push -u origin <local-branch>:<remote-branch>
```

3. Once the code changes are staged on the fork and ready for review, please [submit](https://help.github.com/en/articles/creating-a-pull-request) a [Pull Request](https://help.github.com/en/articles/about-pull-requests) (PR) to merge the changes from a branch of the fork into a selected branch of upstream.

- Exercise caution when selecting the source and target branches for the PR.
- Creation of a PR creation kicks off the code review process.

4. Holoscan CLI maintainers will review the PR and accept the proposal if changes meet Holoscan CLI standards.

Thanks in advance for your patience as we review your contributions. We do appreciate them!

### Development Environment

Holoscan CLI uses [Poetry](https://python-poetry.org/) for package and dependency management. After installing Poetry, run the following commands to get started:

```bash
# Create virtual environment
poetry shell

# Install dependencies
poetry install

# Configure pre-commmit hooks
pre-commit install

# Run pre-commit against all files
pre-commit run --all-files

# Build sdist package
poetry build

# Run tests
poetry run pytest
```

## Preparing Your Submission

### Coding Guidelines & Linting

All source code contributions must strictly adhere to the Holoscan CLI coding style. This can easily be done with git hooks by using the `pre-commit` commands described in the [Development Environment](#development-environment) section.

## Signing Your Contribution

- We require that all contributors "sign-off" on their commits. This certifies that the contribution is your original work, or you have rights to submit it under the same license, or a compatible license.

- Any contribution which contains commits that are not Signed-Off will not be accepted.

- To sign off on a commit you simply use the `--signoff` (or `-s`) option when committing your changes:

  ```bash
  $ git commit -s -m "Add cool feature."
  ```

  This will append the following to your commit message:

  ```
  Signed-off-by: Your Name <your@email.com>
  ```

- Full text of the DCO:

  ```
    Developer Certificate of Origin
    Version 1.1

    Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
    1 Letterman Drive
    Suite D4700
    San Francisco, CA, 94129

    Everyone is permitted to copy and distribute verbatim copies of this license document, but changing it is not allowed.
  ```

  ```
    Developer's Certificate of Origin 1.1

    By making a contribution to this project, I certify that:

    (a) The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or

    (b) The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or

    (c) The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.

    (d) I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.
  ```

## Testing

### Writing & Running Tests

#### Unit Tests

Ideally add unit test when possible using [Pytest](https://docs.pytest.org/). Run unit tests using `poetry run pytest`.

## Reporting issues

Please open a [HoloHub Issue Request](https://github.com/nvidia-holoscan/holoscan-cli/issues) to request an enhancement, bug fix, or other change in HoloHub.

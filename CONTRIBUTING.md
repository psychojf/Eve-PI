# Contributing to EVE PI Template Generator

Thank you for your interest in contributing! This project is designed to be approachable for new contributors while maintaining quality for users.

## How to Contribute

1. Open an issue if you want to:
   - Report a bug
   - Suggest a new feature
   - Ask for help or clarification

2. If you want to contribute code:
   - Fork the repository
   - Create a branch with a descriptive name, e.g. `fix/planet-radius-cache` or `feature/market-price-fetch`
   - Make your changes in the fork
   - Submit a pull request back to this repository

## Code Style

- Follow the existing Python style in `PI.py` and the modules under `src/`.
- Keep code simple and readable.
- Comments and docstrings in this codebase are written in French and explain the why. Text shown in the interface stays in English.
- Every font size goes through `_fs()`, so the text-size setting reaches it.
- `src/services` holds the calculations and never imports Tk; `src/ui` and `PI.py` hold the interface. Keep that split.
- Use meaningful variable and function names.

## Testing

- The test suite is not part of this repository (see `.gitignore`), so there is nothing to run before opening a pull request.
- Explain how to reproduce the issue or validate your fix in the PR description. For a change to a generated colony, attach the template JSON before and after.
- The colony engine is shared with the web version of the tool and the two are expected to build identical colonies; say so in the PR if a change alters what the generator outputs.

## Dependencies

- The project depends on the Python standard library plus `Pillow`, `pystray` and `certifi` (`requirements.txt`).
- If you add a dependency, document it clearly in `README.md` and ensure the package is necessary. The tool ships as a single executable, so its size matters.

## GitHub Workflow

- Keep pull requests focused and small whenever possible.
- Rebase or merge from the default branch if the base branch has changed significantly.
- Include a short summary of your changes and the problem they solve.

## Documentation

- Update `README.md` and `how_to.txt` for any user-facing changes.
- If you add or modify features, document how to use them clearly.

## Code of Conduct

By contributing, you agree to follow the project's [Code of Conduct](CODE_OF_CONDUCT.md).
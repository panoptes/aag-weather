# Changelog

All notable changes to this project will be documented in this file.

This project uses Git tags for releases. Entries below are derived from the Git history.

## [Unreleased]

- Cleanup : formatting and linting (b538d06)
- Update build tools (#30) (8dda317)

## [v0.0.5] - 2024-05-19

- Updating pypi api token publishing (6526bb9)

## [v0.0.4] - 2024-05-19

- Updating GHAs (7e0bb23)
- Missing annotated types (38d3924)
- BaseSettings import fix (9427ac4)
- Test str (ae57e43)
- Dumb package name. (1516e96)
- Better testting. (d094249)
- Add `dotenv` depenency directly and remove (incorrect) extras from `pydantic`. (feb0ca6)
- Fixing the opening of the serial port so it respects the `connect` param. Fixing tests for some coverage. (e8a4952)
- Don't specify delimeter for json. (8409a73)
- Properly Allow different formats. (a861fe1)
- Allow different formats. (cf50119)
- Round the values so we don't have ridiculous precision. (c73a474)
- Make the `get_errors` call optional and `False` by default (I've never seen an error). (e526bde)
- Removing solitary print command. (ca15890)
- Better interrupt for quitting. (972445b)
- Average 3 times. (a9170c8)
- Average the readings. (479f695)

## [v0.0.3] - 2023-09-02

- Add safety check (#28) (80b9377)
- Change default repeat time to 30 seconds. Should be user configurable. (07d5974)
- Skip initial repeat reading because of race condition with connect. (85688da)

## [v0.0.2] - 2023-08-27

- Set default for params so strining works (90ebf67)
- Error checking and docs (#27) (8e0870a)
- Update README.md (a170f78)
- Update create-release.yaml (6ece6f0)

## [v0.0.1] - 2023-05-30

Highlights from initial extraction and modernization:

- Redux of project structure and packaging (#26) (bdc2761)
- FastAPI server for publishing readings (e4bb2fc)
- Return the full data structure (ce74918)
- Add from_yaml (f9603f1)
- Dockerize (d5b8320)
- JSON output and format flexibility (f623fe7, 95020e3, cf50119, a861fe1, 8409a73)
- Safety options and error handling improvements (#21, #19) (c0d6ea5, 58e5c88)
- Dependency and security bumps (pyyaml/jinja2) (0d1e9e7, 020d2e5)
- Early Flask server and service utilities (4bf38a5, d4e9708)
- Initial import from PANOPTES/POCS and early tooling (19ff85b, 1cb8a96)

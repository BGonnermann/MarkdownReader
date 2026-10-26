# Security policy

## Supported versions

Fixes go into the next release from `main`. Only the
[latest release](https://github.com/BGonnermann/MarkdownReader/releases/latest)
is supported.

## Reporting a vulnerability

Please report privately rather than opening a public issue, through
[GitHub's private vulnerability reporting](https://github.com/BGonnermann/MarkdownReader/security/advisories/new).

A useful report says what a malicious document can make the application do, and
includes the smallest Markdown file that demonstrates it. Expect a first reply
within a week.

## What counts

This is a desktop reader, so the threat is a Markdown file from someone else.
These are in scope:

- Content that runs code, opens a program, or reaches the network or another host
  without confirmation
- Content that reads or writes files outside the one being edited
- Losing or corrupting the file being edited

These are not:

- A link that opens only after you confirm the prompt
- Images loaded from the folder the document is in
- Anything that needs the attacker to already control the account running the app

## What the application does about it

- Links to local files, programs, and non-web protocols ask before opening
- The preview refuses images and other resources from UNC paths and remote URLs
- Saves are written to a temporary file and swapped into place
- Releases are built by GitHub Actions from a tagged commit and carry a signed
  attestation (`gh attestation verify <zip> --repo BGonnermann/MarkdownReader`)

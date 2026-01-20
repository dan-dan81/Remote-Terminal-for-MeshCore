## [1.5.0] - 2026-01-19

Feature: Network visualizer

## [1.4.1] - 2026-01-19

Feature: Add option to attempt historical DM decrypt on new-contact advertisement (disabled by default)
Feature: Server-side preference management for favorites, read status, etc.
UI: More compact hop labelling
Bugfix: Misc. race conditions and websocket handling
Bugfix: Reduce fetching cadence by loading all contact data at start to prevent fetches on advertise-driven update

## [1.4.0] - 2026-01-18

UI: Improve button layout for room searcher
UI: Improve favicon coloring
UI: Improve status bar button layout on small screen
Feature: Show multi-path hop display with distance estimates
Feature: Search rooms and contacts by key, not just name
Bugfix: Historical DM decryption now works as expected
Bugfix: Don't double-set active conversation after addition; wait for backend room name normalization

## [1.3.1] - 2026-01-17

UI: Rework restart handling
Feature: Add `dutycyle_start` command to logged-in repeater session to start five min duty cycle tracking
Bug: Improve error message rendering from server-side errors
UI: Remove octothorpe from channel listing

## [1.3.0] - 2026-01-17

Feature: Rework database schema to drop unnecessary columns and dedupe payloads at the DB level
Feature: Massive frontend settings overhaul. It ain't gorgeous but it's easier to navigate.
Feature: Drop repeater login wait time; vestigial from debugging a different issue

## [1.2.1] - 2026-01-17

Update: Update meshcore-hashtag-cracker to include sender-identification correctness check

## [1.2.0] - 2026-01-16

Feature: Add favorites

## [1.1.0] - 2026-01-14

Bugfix: Use actual pathing data from advertisements, not just always flood (oops)
Bugfix: Autosync radio clock periodically to prevent drift (would show up most commonly as issues with repeater comms)

## [1.0.3] - 2026-01-13

Bugfix: Add missing test management packages
Improvement: Drop unnecessary repeater timeouts, and retain timeout for login only -- repeater ops are faster AND more reliable!

## [1.0.2] - 2026-01-13

Improvement: Add delays between router ops to prevent traffic collisions

## [1.0.1] - 2026-01-13

Bugixes: Cleaner DB shutdown, radio reconnect contention, packet dedupe garbage removal

## [1.0.0] - 2026-01-13

Initial full release!


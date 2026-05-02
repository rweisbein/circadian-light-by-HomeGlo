# Privacy Policy

**Effective date:** May 2, 2026

Circadian Light by HomeGlo (the "App") is published by HomeGlo as a companion to the Circadian Light Home Assistant add-on. This page describes what the App does and does not do with your data.

## What the App is

The App is a viewer for your own Home Assistant instance. It loads the Circadian Light add-on's web interface in an embedded browser (`WKWebView`) and displays it as a native iOS app. All communication happens between your phone and the Home Assistant server you configure — nothing is routed through HomeGlo's servers, because there are no HomeGlo servers involved.

## What we do not collect

- We do **not** collect personal information.
- We do **not** transmit usage data, telemetry, analytics, or crash reports to HomeGlo or any third party.
- We do **not** track your activity across other apps or websites.
- We do **not** sell, share, or monetize data of any kind.

## What is stored locally on your device

The App stores two pieces of configuration on your phone using iOS's standard `UserDefaults` and `WKWebsiteDataStore`:

1. **Your Home Assistant URL** — the address of your own Home Assistant server, so the App knows where to load. You set this in the App's settings.
2. **Standard web cookies and session data** — the same way Safari would, so your Home Assistant login persists between launches.

Neither of these ever leaves your device.

## Network access

The App talks only to the Home Assistant server URL you configure. iOS will prompt you for "Local Network" access permission the first time the App tries to reach a `.local` hostname (e.g., `homeassistant.local`); this permission is used solely to discover your Home Assistant on your home Wi-Fi.

## Children's privacy

The App is not directed to children under 13 and we do not knowingly collect data from anyone, including children.

## Changes to this policy

If this policy changes, the updated version will appear at the same URL with a new effective date.

## Contact

Questions about this policy: rweisbein@gmail.com

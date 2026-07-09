# Agent Packaging

This directory contains deployment scaffolding for turning the edge agent into a background service.

## Windows

- Run the Node edge agent with `node dist/server.js`
- Keep the Python recognizer service beside it or bundle it as a second service
- Use a service wrapper such as NSSM or WinSW to launch both processes on login/startup

## macOS

- Use a LaunchAgent for user-session startup
- Use a LaunchDaemon if you want it to run before user login
- Keep SQLite data under a writable application support directory

## Notes

- The agent is designed to stay local and offline-first
- The VPS should receive only synced records and control data
- Camera configuration, attendance, and recognition data live in SQLite on the edge machine

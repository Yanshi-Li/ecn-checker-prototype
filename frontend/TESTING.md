# Frontend behavior tests

Run the frontend tests from the repository root:

```powershell frontend/TESTING.md
npm --prefix frontend test
```

Or from the frontend directory:

```powershell frontend/TESTING.md
npm test
```

The suite uses Vitest, jsdom, and Testing Library. It renders the real React interface and simulates user input while mocking HTTP responses, so it does not require Flask or PostgreSQL to be running. Add assertions for visible outcomes and user-observable requests; avoid testing private React state or implementation details.

The current workflow test covers a tester signing in and reaching the pre-check workspace. Continue expanding coverage through rendered interactions as React workflows are added.

# ConceptTrail frontend

React + TypeScript web app for students and teachers. It talks only to the ConceptTrail HTTP API
(`VITE_API_BASE_URL`); it never connects to the database, Redis or the model server.

- Start, stop and test: [`../docs/LOCAL_DEVELOPMENT.md`](../docs/LOCAL_DEVELOPMENT.md)
- API usage, auth, states, Bell Ringer and heatmap: [`../docs/FRONTEND_INTEGRATION.md`](../docs/FRONTEND_INTEGRATION.md)
- What was changed from the original Antigravity build and why: [`../docs/FRONTEND_UI_AUDIT.md`](../docs/FRONTEND_UI_AUDIT.md)

```sh
npm ci
npm run dev        # http://localhost:5173 (expects the demo backend on http://localhost:8020)
npm test           # unit tests + OpenAPI contract test
npm run build      # type-check and production build into dist/
npx playwright test  # end-to-end journeys against the running stack
```

Rules for changes here:

- Add API calls only in `src/api/endpoints.ts` (the contract test checks every path against
  `docs/openapi/openapi-v1.json`) and expose them through `src/api/hooks.ts`.
- Show `null` as "no evidence yet", never as 0. Mastery is a provisional estimate, not a grade.
- Treat `503 feature_not_enabled` as "not available yet", never as success or as a crash.
- Use the tokens in `tailwind.config.js` and the classes in `src/index.css`; avoid raw hex values.
- Use the official logo only through `src/components/brand/BrandLogo.tsx`.
- Keep motion short and transform/opacity-only; it must respect reduced motion.

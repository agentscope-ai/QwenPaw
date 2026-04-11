---
name: etoro
version: 1.0.0
description: Enables agents to interact with the eToro API to access market data, portfolio and social features, and execute trades programmatically.
homepage: https://api-portal.etoro.com/
metadata: {"copaw":{"emoji":"📈","category":"finance","api_base":"https://public-api.etoro.com/api/v1"}}
---

# eToro Public API

Base URL: `https://public-api.etoro.com/api/v1`

## About

This skill allows to interact with the user's eToro account programatically, including executing trades.

## Authentication & Required Headers

**Keys (request from the user on install)**
- **Public API Key**: application
- **User Key**: user account
- **Environment**: Real Portfolio or Virtual Portfolio (real/demo)

**Key generation (user-facing):**
1. Log in to eToro.
2. Settings > Trading.
3. Create New Key.
4. Choose **Environment** (Real or Virtual/Demo) and **Permissions** (Read or Write).
5. Verify identity and copy the generated User Key.

**Headers (every request):**
- `x-request-id`: unique UUID per request
- `x-api-key`: Public API Key (<PUBLIC_KEY>)
- `x-user-key`: User Key (<USER_KEY>)

Example:
```bash
curl -X GET "https://public-api.etoro.com/api/v1/watchlists" \
  -H "x-request-id: <UUID>" \
  -H "x-api-key: <PUBLIC_KEY>" \
  -H "x-user-key: <USER_KEY>"
```

## Request Conventions
- **All paths below are relative to the Base URL** (which already includes `/api/v1`).  
  Example: `GET /watchlists` means `GET https://public-api.etoro.com/api/v1/watchlists`.
- Query params go in the URL, path params go in the URL path.
- For query params that are documented as `array`, send them as **comma-separated values** (e.g., `instrumentIds=1001,1002`).
- Pagination patterns vary by endpoint:
  - Search: `pageNumber`, `pageSize`
  - People search & trade history: `page`, `pageSize`
  - Feeds: `take`, `offset`
  - Watchlist items listing: `pageNumber`, `itemsPerPage`
- **Casing matters** for request bodies:
  - Trading execution uses **PascalCase** fields (e.g., `InstrumentID`, `IsBuy`, `Leverage`).
  - Market close body uses `InstrumentId` (capital I, lowercase d).
  - Watchlist items use `ItemId`, `ItemType`, `ItemRank`.
  - Feeds post body uses lower camel (`owner`, `message`, `tags`, `mentions`, `attachments`).
- Some responses may use different casing for similar concepts (e.g., `instrumentId` vs `InstrumentID`). When extracting IDs, handle both if present.

## Demo vs Real Trading

- Use **demo execution endpoints** (contain `/demo/`) for testing and paper trading.
- Use **non-demo execution endpoints** for real trading.
- For portfolio/PnL:
  - Demo: `/trading/info/demo/*`
  - Real: `/trading/info/portfolio` and `/trading/info/real/pnl`
- Ensure your key environment matches the endpoint (Virtual vs Real). Each User Key is associated with a specific environment.

## Use Defaults

- Important: You don't need to specify all parameters. If the user doesn't specify leverage for example, don't send it on the API request. 

## Quick Start (Demo Trade)

1) **Resolve `instrumentId`** using search.  
`fields` is required on search requests.

```bash
curl -X GET "https://public-api.etoro.com/api/v1/market-data/search?internalSymbolFull=BTC&fields=instrumentId,internalSymbolFull,displayname" \
  -H "x-api-key: <PUBLIC_KEY>" \
  -H "x-user-key: <USER_KEY>" \
  -H "x-request-id: <UUID>"
```

2) **Place a demo market order by amount** (PascalCase body):
```bash
curl -X POST "https://public-api.etoro.com/api/v1/trading/execution/demo/market-open-orders/by-amount" \
  -H "x-api-key: <PUBLIC_KEY>" \
  -H "x-user-key: <USER_KEY>" \
  -H "x-request-id: <UUID>" \
  -H "Content-Type: application/json" \
  -d '{
    "InstrumentID": 100000,
    "IsBuy": true,
    "Leverage": 1,
    "Amount": 100
  }'
```

## Common IDs

- `instrumentId`: from Search or Instruments metadata
- `positionId`: from Portfolio endpoints
- `orderId`: from execution responses or Portfolio endpoints
- `marketId`: used by instrument feed endpoints (typically available in instrument metadata/search fields)
- `userId`: numeric eToro user ID (often referred to as **CID** in responses; discover via People endpoints/search)
- `watchlistId`: from watchlists list/create endpoints
- `subPortfolioId`: from Agent Portfolio endpoints (UUID)

## Market Data (Requests)

**Search instruments**
- `GET /market-data/search`
- Required query: `fields` (comma-separated list of instrument fields to return)
- Optional: `searchText`, `pageSize`, `pageNumber`, `sort`
- The Search endpoint supports filtering by fields returned in results; for exact symbol lookup, use `internalSymbolFull` as a query param and verify the exact match.
- Recommended minimal `fields` when you need IDs: include the instrument identifier (may appear as `instrumentId` or `InstrumentID`), plus `internalSymbolFull` and `displayname` (and `marketId` if you plan to use Feeds).

**Metadata**
- `GET /market-data/instruments`  
  Filters: `instrumentIds`, `exchangeIds`, `stocksIndustryIds`, `instrumentTypeIds`.

**Prices & history**
- `GET /market-data/instruments/rates`  
  Required: `instrumentIds` (comma-separated).
- `GET /market-data/instruments/history/closing-price`  
  Returns historical closing prices for all instruments (bulk).
- `GET /market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`  
  `direction`: `asc` or `desc`. `candlesCount` max 1000.  
  Supported interval values typically include: OneMinute, FiveMinutes, FifteenMinutes, ThirtyMinutes, OneHour, OneDay, OneWeek.

**Reference data**
- `GET /market-data/exchanges` (optional `exchangeIds`)
- `GET /market-data/instrument-types`
- `GET /market-data/stocks-industries` (optional `stocksIndustryIds`)

## Trading Execution (Requests)

> Requires a key with appropriate permissions (typically **Write**) and the correct environment (Demo vs Real).

### Market Open Orders (by amount)

Endpoints:
- `POST /trading/execution/demo/market-open-orders/by-amount`
- `POST /trading/execution/market-open-orders/by-amount`

Body (PascalCase, JSON):
- **Required:** `InstrumentID`, `IsBuy`, `Leverage`, `Amount`
- **Optional:** `StopLossRate`, `TakeProfitRate`, `IsTslEnabled`, `IsNoStopLoss`, `IsNoTakeProfit`

### Market Open Orders (by units)

Endpoints:
- `POST /trading/execution/demo/market-open-orders/by-units`
- `POST /trading/execution/market-open-orders/by-units`

Body (PascalCase, JSON):
- **Required:** `InstrumentID`, `IsBuy`, `Leverage`, `AmountInUnits`
- **Optional:** `StopLossRate`, `TakeProfitRate`, `IsTslEnabled`, `IsNoStopLoss`, `IsNoTakeProfit`

### Cancel Market Open Orders

Endpoints:
- `DELETE /trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /trading/execution/market-open-orders/{orderId}`

### Market Close Orders

Endpoints:
- `POST /trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /trading/execution/market-close-orders/positions/{positionId}`
- `DELETE /trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /trading/execution/market-close-orders/{orderId}`

Body (JSON):
- **Required:** `InstrumentId`
- **Optional:** `UnitsToDeduct` (number or `null`)

Partial close: set `UnitsToDeduct`.  
Full close: set `UnitsToDeduct` to `null`.  
You must close by `positionId`, not by symbol.

### Market-if-touched (Limit) Orders

Endpoints:
- `POST /trading/execution/demo/limit-orders`
- `DELETE /trading/execution/demo/limit-orders/{orderId}`
- `POST /trading/execution/limit-orders`
- `DELETE /trading/execution/limit-orders/{orderId}`

Body (PascalCase, JSON):
- **Required:** `InstrumentID`, `IsBuy`, `Leverage`, **`Rate`**, and **one of** `Amount` **or** `AmountInUnits`
- **Optional:** `StopLossRate`, `TakeProfitRate`, `IsTslEnabled`, `IsNoStopLoss`, `IsNoTakeProfit`
- **Do not send:** `IsDiscounted`, `CID`

## Trading Info & Portfolio (Requests)

- `GET /trading/info/demo/pnl`
- `GET /trading/info/real/pnl`
- `GET /trading/info/demo/portfolio`
- `GET /trading/info/portfolio`  
  Use these to discover `positionId` and `orderId` for close/cancel flows.
- `GET /trading/info/trade/history`  
  Required: `minDate` (YYYY-MM-DD). Optional: `page`, `pageSize`.

## Watchlists (Requests)

**User watchlists**
- `GET /watchlists`  
  Optional: `itemsPerPageForSingle`, `ensureBuiltinWatchlists`, `addRelatedAssets`.
- `GET /watchlists/{watchlistId}`  
  Optional: `pageNumber`, `itemsPerPage`.
- `POST /watchlists`  
  Query: `name` (required), `type`, `dynamicQuery` (optional). (Uses query params, not a JSON body.)
- `PUT /watchlists/{watchlistId}`  
  Query: `newName` (required). (Uses query params, not a JSON body.)
- `DELETE /watchlists/{watchlistId}`

**Watchlist items (body schema)**

`WatchlistItemDto` fields:
- `ItemId` (required, int)
- `ItemType` (required, string: `Instrument` or `Person`)
- `ItemRank` (optional, int)

Endpoints:
- `POST /watchlists/{watchlistId}/items`
- `PUT /watchlists/{watchlistId}/items`
- `DELETE /watchlists/{watchlistId}/items`

Example body:
```json
[
  { "ItemId": 12345, "ItemType": "Instrument", "ItemRank": 1 },
  { "ItemId": 67890, "ItemType": "Instrument", "ItemRank": 2 }
]
```

**Default watchlists**
- `POST /watchlists/default-watchlist/selected-items`
- `GET /watchlists/default-watchlists/items`  
  Optional: `itemsLimit`, `itemsPerPage`.
- `POST /watchlists/newasdefault-watchlist`  
  Query: `name` (required), `type`, `dynamicQuery` (optional).
- `PUT /watchlists/setUserSelectedUserDefault/{watchlistId}`
- `PUT /watchlists/rank/{watchlistId}`  
  Query: `newRank` (required).

**Public watchlists**
- `GET /watchlists/public/{userId}`
- `GET /watchlists/public/{userId}/{watchlistId}`

## Feeds (Requests)

**Read feeds**
- `GET /feeds/instrument/{marketId}`  
  Optional: `requesterUserId`, `take`, `offset`, `badgesExperimentIsEnabled`, `reactionsPageSize`.
- `GET /feeds/user/{userId}`  
  Optional: `requesterUserId`, `take`, `offset`, `badgesExperimentIsEnabled`, `reactionsPageSize`.

Notes:
- `marketId` is associated with an instrument (typically available via instrument metadata/search if you include it in `fields`).
- `userId` is a numeric user identifier (CID). If you only have a username, discover the numeric ID via People endpoints (see User Info & Analytics).

**Create post**
- `POST /feeds/post`
- Body fields (lower camel, JSON):
  - `owner` (int)
  - `message` (string)
  - `tags`: `{ "tags": [{ "name": "...", "id": "..." }] }`
  - `mentions`: `{ "mentions": [{ "userName": "...", "id": "...", "isDirect": true }] }`
  - `attachments`: array of objects with `url`, `title`, `host`, `description`, `mediaType`, and optional `media`.

Minimal example:
```json
{ "message": "Hello eToro feed!" }
```

## Curated Lists & Recommendations (Requests)

- `GET /curated-lists`
- `GET /market-recommendations/{itemsCount}`

## Popular Investors (Copiers)

- `GET /pi-data/copiers`

## User Info & Analytics (Requests)

- `GET /user-info/people`  
  Optional: `usernames`, `cidList`.  
  Use this to map **username ↔ CID (userId)** when you need numeric `userId` for feeds/public watchlists.
- `GET /user-info/people/search`  
  Required: `period`. Optional: `page`, `pageSize`, `sort`, `popularInvestor`, `gainMax`, `maxDailyRiskScoreMin`, `maxDailyRiskScoreMax`, `maxMonthlyRiskScoreMin`, `maxMonthlyRiskScoreMax`, `weeksSinceRegistrationMin`, `countryId`, `instrumentId`, `instrumentPctMin`, `instrumentPctMax`, `isTestAccount`, and other filters.
- `GET /user-info/people/{username}/gain`
- `GET /user-info/people/{username}/daily-gain`  
  Required: `minDate`, `maxDate`, `type` (`Daily` or `Period`).
- `GET /user-info/people/{username}/portfolio/live`
- `GET /user-info/people/{username}/tradeinfo`  
  Required: `period` (e.g., `LastTwoYears`).

## Agent Portfolios (Sub-Portfolios)

Agent portfolios are dedicated sub-accounts with their own virtual balance, enabling agents to trade independently via copy-trading. `investmentAmountInUsd` is deducted from **your** balance to copy the sub-portfolio — positions mirror proportionally (e.g. $2k investment / $10k virtual balance = 20% sizing). The `userToken` secret is **only returned at creation time**.

- `GET /sub-portfolios` — list all your agent portfolios.
- `POST /sub-portfolios` — create agent portfolio.  
  Required body: `investmentAmountInUsd`, `subPortfolioName` (6–10 chars), `userTokenName`, `scopeIds`.  
  Optional: `subPortfolioDescription`, `ipsWhitelist`, `expiresAt`.
- `DELETE /sub-portfolios/{subPortfolioId}` — permanently delete (revokes tokens, stops mirror).
- `POST /sub-portfolios/{subPortfolioId}/user-tokens` — create token.  
  Required body: `userTokenName`, `scopeIds`. Optional: `ipsWhitelist`, `expiresAt`.
- `PATCH /sub-portfolios/{subPortfolioId}/user-tokens/{userTokenId}` — update token (at least one of: `scopeIds`, `ipsWhitelist`, `expiresAt`).
- `DELETE /sub-portfolios/{subPortfolioId}/user-tokens/{userTokenId}` — revoke token.

Scope IDs: 200 = real:read, 201 = demo:read, 202 = real:write, 203 = demo:write.

## Responses & Schemas

For response schemas and full examples, refer to:
- https://api-portal.etoro.com/
- MCP server: `https://api-portal.etoro.com/mcp`

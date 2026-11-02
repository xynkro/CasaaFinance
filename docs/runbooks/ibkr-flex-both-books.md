# Runbook — Sarah's book from IBKR Flex (both accounts, fresh daily)

Today Caspar's book is pulled fresh every day by `ibkr-flex-sync` (Flex Web
Service: a token plus a query id, no TWS, no login). Sarah's account is not in
that query, so on GitHub Actions there is nothing to carry forward from and her
cash and share counts sit frozen while the Yahoo job only re-marks prices.

The sync script now builds her book from Flex as soon as it can see her data,
and stays inert until then. There are two ways to give it that data. Only you
can do either, because both need a Client Portal login.

- **Path A: her account is visible under your login.** Add it to the existing
  query. No new secret.
- **Path B: she has her own login.** She enables Flex, makes a token and her own
  query, and you store two secrets.

This repo is public. Never paste a token, query id, account id, balance or share
count into an issue, commit, PR or chat that others can see.

## Step 1 — Is her account under your login?

1. Log in to the Client Portal as Caspar.
2. Go to **Performance & Reports > Flex Queries** (or **Menu > Reporting > Flex
   Queries**). IBKR's guide says that if the login manages multiple accounts, an
   **Account Selector** opens. Check whether Sarah's account is listed there (the
   account switcher at the top of the portal shows the same list).
3. Listed: use **Path A**. Not listed: use **Path B**.

## Path A — widen the existing query

1. Flex Queries > Activity Flex Query panel > open the existing query for editing.
2. **Delivery Configuration > Accounts > Add/Edit Accounts**: tick Sarah's account
   as well as Caspar's. Leave Format as **XML**.
3. Make sure every section carries the fields in "Fields the parser reads" below,
   in particular `accountId` and `currency` in **every** section, and `fxRateToBase`
   and `currency` in Open Positions. Rows without an `accountId` cannot be told
   apart in a two-account report.
4. Save. Go to "Verify" below. No secret is needed: the script splits the report
   by `accountId`, and Caspar's numbers are scoped to his own account id.

## Path B — her own login, token and query

Log in to the Client Portal **as Sarah**.

1. **Enable the service.** Performance & Reports > Flex Queries > **Flex Web
   Service Configuration** (gear icon). Turn the service on and save.
2. **Generate a token.**
   - **Should Expire After**: the default is 6 hours, which is useless here. Pick
     the longest option the dropdown offers (a third-party guide shows 1 year;
     IBKR's page does not state a maximum, so read what your dropdown offers).
   - **Valid For IP Address**: leave blank. GitHub runners do not have a fixed IP.
   - Click **Generate New Token** and copy it. Generating a new token invalidates
     the previous one.
   - **Put the expiry date in your calendar and renew 2 to 4 weeks before it.** An
     expired token returns error 1012 "Token has expired"; her book then goes
     back to carry-forward (stale, not wrong) and Caspar's sync is unaffected.
     Renewing means generating a new token and re-running the `gh secret set`
     for `IB_FLEX_TOKEN_SARAH` below.
3. **Create the query.** Flex Queries > **+** in the Activity Flex Query panel.
   - Name it anything. Add the sections and fields under "Fields the parser reads".
   - **Delivery Configuration**: Accounts = her account only; **Format = XML**;
     **Period = Last Business Day**. Leave General Configuration at defaults.
   - Continue > Create. Note the numeric **Query ID** the portal assigns. IBKR's
     guide does not say where it is shown, so look at the query's row or its
     details icon.

### Fields the parser reads

The portal shows friendly labels (for example "Quantity" is `position`, "FIFO
Unrealized PNL" is `fifoPnlUnrealized`, "FX Rate to Base" is `fxRateToBase`).
The names below are the XML attributes in `scripts/ibkr_flex_sync.py`.

| Section (portal label per IBKR's reference) | Attributes read |
|---|---|
| **Account Information** | `accountId`, `currency` |
| **Open Positions** (Level of Detail: **Summary** only, never Lot) | `accountId`, `assetCategory`, `symbol`, `position`, `markPrice`, `positionValue`, `costBasisPrice`, `costBasisMoney`, `fifoPnlUnrealized`, `currency`, `fxRateToBase`, `levelOfDetail`, and for options `putCall`, `strike`, `expiry`, `multiplier`, `underlyingSymbol` |
| **Net Asset Value (NAV) Summary in Base** (this is the section that produces `EquitySummaryByReportDateInBase`) | `accountId`, `currency`, `reportDate`, `cash`, `stock`, `total`, and `options` (recommended) |

Notes:

- `costBasisMoney` matters: Flex has returned `costBasisPrice` empty before, and the
  script derives the per-share cost from `costBasisMoney` when it does.
- `fxRateToBase` and `currency` are what make her SGD book correct. Open Positions
  values are in each position's own currency; the script uses `fxRateToBase` only to
  total the SGD figures. Without them her book is rejected rather than guessed.
- Do not tick `name` or address fields in Account Information. They are not needed.
- The NAV section's label comes from IBKR's Activity Flex Query Reference. If your
  portal words it differently, copy whichever section Caspar's existing query
  already uses for cash, stock and total.
- Ticking both Summary and Lot detail returns every position twice. The script drops
  Lot rows when Summary rows exist, but do not rely on that.

### Check the query before storing secrets (optional, local only)

Run the saved query in the portal (Run icon, Format XML) and search the output for
`fxRateToBase=`, `costBasisMoney=`, `markPrice=`, `fifoPnlUnrealized=`, `currency=`
and `total=`. Or run it from your own terminal. This prints her real holdings, so
keep the output local:

```bash
printf 'Sarah Flex token: '; read -rs IB_FLEX_TOKEN; echo; export IB_FLEX_TOKEN
python scripts/ibkr_flex_sync.py --query <her-query-id> --json | head -80
unset IB_FLEX_TOKEN
```

Every position should show a `currency` and a non-null `fx_to_base`.

### Store the two secrets

`gh secret set` with no `--body` asks for the value at a hidden prompt, so nothing
goes on the command line or into shell history. This repo belongs to the `xynkro`
GitHub account; if `gh auth status` shows another account as active, run
`gh auth switch --user xynkro` first.

```bash
gh secret set IB_FLEX_TOKEN_SARAH    --repo xynkro/CasaaFinance   # paste her token at the prompt
gh secret set IB_FLEX_QUERY_ID_SARAH --repo xynkro/CasaaFinance   # paste her query id at the prompt
gh secret list --repo xynkro/CasaaFinance | grep SARAH            # names only, never values
```

Both must be set. With only one, the script ignores them and says which is missing.

## Verify

```bash
gh workflow run ibkr-flex-sync.yml --repo xynkro/CasaaFinance
gh run watch --repo xynkro/CasaaFinance
```

Open the run log and find the one line starting `sarah:`. It never contains values.

| Line says | Meaning / fix |
|---|---|
| `fresh from Flex (second report)` or `(split from the main report by accountId)` | Done. Check `snapshot_sarah` and `positions_sarah` in the Sheet for today. |
| `carried forward (no Sarah credentials set, her account not in the main report)` | Nothing configured yet, or Path A's account was not saved into the query. |
| `... is not set` | Only one of the two secrets exists. |
| `second report unusable (RuntimeError: SendRequest failed ... 1012 ...)` | Token expired or invalid. Generate a new one and re-set the secret. |
| `... 1018 / 1019 / 1001 ...` | IBKR is busy or still generating. Re-run later. |
| `no rows for her account in the report` | The query returns another account or nothing. Check Accounts in Delivery Configuration. |
| `no equity summary with total + cash` | The NAV section or its `cash` / `total` fields are missing. |
| `base currency is X, expected SGD` or `base currency not in report` | Add `currency` to Account Information and the NAV section, and check the account base. |
| `a position has no fxRateToBase` | Add FX Rate to Base to Open Positions. |
| `equity summary shows holdings but no open positions came back` | Open Positions is missing or empty. |
| `HTTPError`, `ConnectionError`, `Timeout` | Network or IBKR outage. Only the class name is logged, because the URL contains the token. |

Whatever the line says, Caspar's sync completes and the job's exit code is his.
When her data is missing or incomplete her Sheet rows are left untouched, never
overwritten with an empty book.

## Limits, stated honestly

- **Flex is end-of-day.** IBKR's Flex Web Service documentation says Activity
  Statement queries are updated once daily at close of business, and that
  availability varies with system load. Plan on around midnight ET; that figure is
  an assumption, not an IBKR promise. The job runs at 09:08 UTC. A trade or
  deposit made today shows up in tomorrow's run at the earliest.
- **Only prices are intraday**, and those come from the separate Yahoo job. Her
  cash and share counts are as of the last statement. The Yahoo job re-marks with
  live USD/SGD; Flex totals use IBKR's end-of-day `fxRateToBase`, so a small
  difference between the two is expected.
- **Units.** Position rows (`avg_cost`, `last`, `mkt_val`, `upl`) are written in each
  position's own currency (USD for US names, SGD for SGX), the same as the TWS grab,
  Yahoo job and PWA expect; the PWA converts USD rows to SGD itself. Net liquidation,
  cash and `upl_sgd` are SGD.
- **Unverified.** I could not open the Client Portal, so menu and section labels come
  from IBKR's published guides, not from your screen. IBKR's documentation does not
  say how a multi-account query is laid out in XML. The script accepts either one
  `FlexStatement` per account or rows labelled per account, and rejects her block
  (carry-forward) if it cannot find complete data for her.
- **Read-only.** Flex only reports. There is no order-placement code against IBKR and
  none is added here.

Sources: IBKR Client Portal guides for Flex Queries, the Flex Web Service
configuration and the Activity Flex Query Reference
(ibkrguides.com/orgportal/performanceandstatements/flex.htm and the reporting
reference pages), and IBKR's Flex Web Service introduction.

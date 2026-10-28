# Flow: case-closed email

Emails a ready-to-send message when a case is **Accepted** or **Declined**. Built by hand in Power Automate
(make.powerautomate.com), signed in as the environment user, in **adam's Environment**.

**Demo behaviour.** The claim data holds no customer name or address, so every email goes to the test mailbox
`adam_merhi@icloud.com` and greets "Policyholder". Change the **To** line and the greeting when real customer
fields exist.

**Hold rule.** No email is sent while the second check (the Verifier) disagrees with the decision, or if no check
exists for the decision. A decline the PDS does not support must never go out on its own (the ASIC risk). Releasing a
held case is not built yet (see section 7).

## 1. Name and trigger

Create an **Automated cloud flow**, name it `Case closed email`, trigger **Microsoft Dataverse: When a row is added,
modified or deleted**.

| Setting | Value |
|---|---|
| Change type | Modified |
| Table name | Claims |
| Scope | Organization |
| Select columns | `new_decision` |
| Filter rows | `(new_decision eq 'Accepted' or new_decision eq 'Declined') and new_emailsentat eq null` |

*Select columns* makes the flow fire only when the decision changes, so writing `Email sent at` later does not
re-trigger it. *Filter rows* skips New and In review and any case already emailed.

## 2. Find the matching check

**List rows** (Dataverse), rename the step `Get check`:

| Setting | Value |
|---|---|
| Table name | Decision Checks |
| Filter rows | `new_claimkey eq '@{triggerOutputs()?['body/new_srcrowid']}' and new_decision eq '@{triggerOutputs()?['body/new_decision']}'` |
| Sort by | `createdon desc` |
| Row count | 1 |

## 3. Hold rule

Add a **Condition** named `Safe to send`. Use "edit in advanced mode" and paste:

```
@and(greater(length(outputs('Get_check')?['body/value']), 0), equals(first(outputs('Get_check')?['body/value'])?['new_requiresmanager'], false))
```

- **If yes** continue with step 4.
- **If no** add **Add a new row** (Dataverse) to Claim Notes so the hold is visible in the app's history:
  - Summary `Email held`; Claim key `@{triggerOutputs()?['body/new_srcrowid']}`; Type `Email`; Author `Case closed email flow`
  - Note: `Closure email held: no clean check exists for this decision. A line manager must approve first.`
  - Then stop (Terminate, status Succeeded).

*Until the agent API is connected to the app, no Decision Check rows exist, so every case is held. To test the
emails before then, temporarily replace the condition with:*
`@or(equals(length(outputs('Get_check')?['body/value']), 0), equals(first(outputs('Get_check')?['body/value'])?['new_requiresmanager'], false))`
*and switch it back afterwards.*

## 4. Build the values once

**Initialize variable** x3 (all type String), before the email:

| Name | Value |
|---|---|
| `caseNumber` | `@{concat('CLM-', toUpper(substring(triggerOutputs()?['body/new_srcrowid'], 0, 8)))}` |
| `clauses` | `@{replace(coalesce(first(outputs('Get_check')?['body/value'])?['new_clauses'], ''), ';', ', ')}` |
| `reason` | `@{coalesce(triggerOutputs()?['body/new_decisionreason'], '')}` |

## 5. Send the right template

Add a **Condition** `Accepted?`: `triggerOutputs()?['body/new_decision']` **is equal to** `Accepted`.

Use the **Outlook.com** connector, action **Send an email (V2)** (sign in with your personal Microsoft account).
The trial tenant has no Microsoft 365 mailbox, so the Office 365 Outlook connector will not work. If Outlook.com is not
available, use **Mail: Send an email notification (V3)** with the same fields.

**If yes (Accepted)**

- To: `adam_merhi@icloud.com`
- Subject: `Your claim @{variables('caseNumber')} has been accepted`
- Body (HTML):

```html
<p>Hi Policyholder,</p>
<p>Case <b>@{variables('caseNumber')}</b> has been closed. The decision is for your claim to be <b>accepted</b>.</p>
<p>Claim amount: $@{formatNumber(triggerOutputs()?['body/new_claimamount'], 'N2')}<br>
Loss date: @{formatDateTime(triggerOutputs()?['body/new_lossdate'], 'd MMMM yyyy')}</p>
<p>We pay the amount above your $200 excess (clause 4.1). Policy clauses relied on: @{variables('clauses')}.</p>
<p>If anything in this email looks wrong, or you want to talk to us, just reply.</p>
<p>Kind regards,<br>Claims team</p>
```

**If no (Declined)**

- To: `adam_merhi@icloud.com`
- Subject: `Your claim @{variables('caseNumber')} has been declined`
- Body (HTML):

```html
<p>Hi Policyholder,</p>
<p>Case <b>@{variables('caseNumber')}</b> has been closed. The decision is for your claim to be <b>declined</b>.</p>
<p><b>Why:</b> @{variables('reason')}</p>
<p><b>Policy clauses relied on:</b> @{variables('clauses')}. You can read these clauses in your Product Disclosure Statement.</p>
<p>If you believe this decision is wrong, you can ask us to review it by replying to this email. A different member of our team will look at it again.</p>
<p>Kind regards,<br>Claims team</p>
```

A decline always shows the reason and the clause numbers. If `reason` or `clauses` come out empty, the decline
has no policy basis on record and should not be going out; the hold rule above normally stops this.

## 6. Record that it was sent

After the email (outside the Accepted? condition, in the "yes" branch of `Safe to send`):

1. **Update a row** (Dataverse): Table `Claims`, Row ID `@{triggerOutputs()?['body/new_claimid']}`,
   Email sent at `@{utcNow()}`.
2. **Add a new row** (Dataverse) to Claim Notes: Summary `Email sent`, Claim key
   `@{triggerOutputs()?['body/new_srcrowid']}`, Type `Email`, Author `Case closed email flow`, Note
   `Closure email (@{triggerOutputs()?['body/new_decision']}) sent to adam_merhi@icloud.com`.

The app's notes history then shows the sent or held email with a timestamp.

## 7. Releasing a held case (not built yet)

The line-manager approval step does not exist yet (the banner in the app is display only), so a held case has no
automatic way out: re-saving the same decision writes the same conflicting check and is held again. For now a
manager-approved case is emailed by hand. The natural next step is a `Manager approved` column that the app sets and
that the `Safe to send` condition also accepts.

To resend a case that was already emailed, clear its `Email sent at`, then change the decision to another value and
back.

## 8. Test

1. Save the flow and turn it on. Use **Test, Manually** or just use the app.
2. In the app, save a case as **Accepted** (use a case the Verifier agrees with). Within a minute: one email
   arrives, the case's `Email sent at` is filled, and a "Email sent" entry shows in the notes history.
3. Save another as **Declined** with a PDS clause reason: the declined template arrives with the reason and clauses.
4. Save a case as **Declined** with a made-up reason (for example "Excluded: wear and tear"): the app shows the
   line-manager banner, **no** email arrives, and the history shows "Email held".
5. Re-save an already-emailed case: no second email.

Clean up test cases afterwards (clear the decision and `Email sent at`).

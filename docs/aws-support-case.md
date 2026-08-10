# AWS Support-case (klaar om in te dienen als de laatste poging faalt)

**Waar**: AWS Console → Support → Create case → **Account and billing**
(gratis op elk supportplan) → Service: Billing → Category: Payment issue.

**Subject**: Marketplace subscription fails with INVALID_PAYMENT_INSTRUMENT
despite valid default card and payment profile

**Body** (kopieer/plak):

---

Account: 384268138628 (AWS Europe / EMEA SARL, currency EUR)

We are unable to subscribe to an AWS Marketplace product (Anthropic Claude
Sonnet 4.6, Amazon Bedrock Edition, Product ID prod-ffvjxvh4ltq64). Every
subscription attempt ends after ~10 minutes with:

  INVALID_PAYMENT_INSTRUMENT: A valid payment instrument must be provided.

What we have verified/done already:

1. A valid Mastercard (ending 9324, exp 05/2031) is stored and set as the
   DEFAULT payment method.
2. A payment profile exists for service provider "AWS EMEA - Marketplace"
   with currency USD and the same Mastercard.
3. The Bedrock use-case form for Anthropic models has been submitted
   (authorizationStatus = AUTHORIZED, entitlementAvailability = AVAILABLE).
4. Multiple agreement attempts on Aug 8-9, 2026 (e.g. Agreement ID
   agmt-e3vkiqz643bhdhz8f2usvduok) all failed with the same error; we
   receive "agreement has expired" e-mails with identical start/end dates.
5. There is no SCP or IAM restriction (verified via policy simulation:
   aws-marketplace:Subscribe and ViewSubscriptions are allowed).
6. On Aug 10, 2026 we ADDED A SECOND, NEW valid Mastercard and retried.
   The problem persists identically: within seconds of subscribing we
   receive an "offer accepted" e-mail immediately followed by an
   "agreement has expired" e-mail, and Bedrock still returns
   INVALID_PAYMENT_INSTRUMENT. Marketplace > Manage subscriptions shows
   0 active subscriptions. This confirms the block is NOT a missing card
   on file but a backend payment-authorization / account-verification
   issue on your side.
7. AWS Marketplace > Settings has no separate Marketplace payment method;
   it uses the account default, which is a valid, verified card.

Please check on your side why the payment authorization for Marketplace is
failing (card verification state, processor decline reason, or account
verification status), and advise what is needed to complete the
subscription.

---

**Bijlagen/verwijzingen**: de "agreement expired"-mail van 9 aug (offer
offer-ldnd26nhxx676) meesturen als bijlage helpt.

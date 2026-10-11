# Spike S3: picking the Bedrock vision model for doorbell frames

Date: 2026-10-11 · Account <account-id> (IAM `doorledger-dev`) · us-east-1 · Converse API
Reproduce: `make_images.py` (test set) → `run_eval.py --runs ...` → `run_eval.py --report`
Raw per-image outputs: `results_raw.json`. Computed metrics and error lists: `results_metrics.json`.

## TL;DR

| | Choice |
|---|---|
| **Default model** | `us.amazon.nova-2-lite-v1:0` with **prompt v2** (below). 54/54 frames correct on all 5 fields, about $0.37 per 1,000 frames, p50 1.5 s |
| **Fallback** | `us.amazon.nova-lite-v1:0` at 768 px with prompt v2. Packages and people were 100% correct, but **do not trust its `phone_screen_shown`**. About $0.11 per 1,000 frames, p50 1.1 s |
| **Image size** | Send the full frame to Nova 2 Lite. It bills a flat ~456 image tokens at 1536² and at 768², so downscaling saves no money. At 768 it added one false package on an empty mat. Downscale to 768 only for Nova Lite (tokens drop 2,734 → 1,425, cost −43%) or when upload is the bottleneck |
| **Not worth it** | Nova Pro costs 7× Nova 2 Lite and was no more accurate |
| **Untested (blocked)** | Every Claude model. See "Claude access" below |

## Results (54 frames, temperature 0 where allowed, exact production PROMPT unless marked +v2)

| run | pkg acc | pkg P/R | person acc | person P/R | carry acc | vehicle acc | phone acc | mean acc | JSON fail | p50 ms | p95 ms | in tok | out tok | $/1k frames* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| nova-lite | 94% | 79%/100% | 100% | 100%/100% | 100% | 100% | 93% | 97% | 0/54 | 1386 | 1872 | 2734 | 71 | $0.181 |
| nova-lite@768 | 98% | 92%/100% | 100% | 100%/100% | 98% | 100% | 93% | 98% | 0/54 | 1114 | 1480 | 1425 | 71 | $0.103 |
| nova-lite@768 +v2 ¹ | 100% | 100%/100% | 100% | 100%/100% | 100% | 100% | 91% | 98% | 0/54 | 1104 | 1538 | 1511 | 71 | $0.108 |
| nova-2-lite | 100% | 100%/100% | 100% | 100%/100% | 100% | 100% | 96% | 99% | 0/54 | 1450 | 2004 | 456 | 69 | $0.342 |
| nova-2-lite (repeat) | 100% | 100%/100% | 100% | 100%/100% | 100% | 100% | 94% | 99% | 0/54 | 1453 | 2576 | 456 | 69 | $0.341 |
| nova-2-lite@768 | 98% | 92%/100% | 100% | 100%/100% | 100% | 100% | 96% | 99% | 0/54 | 967 | 2186 | 456 | 70 | $0.342 |
| **nova-2-lite +v2** | **100%** | **100%/100%** | **100%** | **100%/100%** | **100%** | **100%** | **100%** | **100%** | 0/54 | 1500 | 2659 | 537 | 70 | **$0.370** |
| nova-2-lite@768 +v2 | 98% | 92%/100% | 100% | 100%/100% | 100% | 100% | 100% | 100% | 0/54 | 921 | 1700 | 537 | 70 | $0.370 |
| nova-pro | 98% | 100%/91% | 100% | 100%/100% | 100% | 100% | 93% | 98% | 0/54 | 1479 | 1689 | 2734 | 69 | $2.408 |
| nova-pro +v2 | 98% | 100%/91% | 100% | 100%/100% | 100% | 100% | 96% | 99% | 0/54 | 1454 | 2015 | 2820 | 69 | $2.476 |

\* $/1k frames is the measured mean tokens × on-demand price. Prices come from the **AWS Price List bulk API** (`offers/v1.0/aws/AmazonBedrock` and `AmazonBedrockFoundationModels`, us-east-1, published 2026-10-08/10). Prices per 1M tokens, input / output: Nova Lite $0.06 / $0.24 · Nova Pro $0.80 / $3.20 · Nova 2 Lite $0.33 / $2.75 (regional, the rate a `us.` profile pays; `global.` is $0.30 / $2.50, about 9% cheaper) · Stable Image Core $0.04/image. The pricing web page renders through JS and could not be read. Treat the prices as accurate as of 10 Oct but subject to change.
¹ Extra data point: prompt v2 was meant only for the best 2 models (Nova 2 Lite, Nova Pro). This run cost under $0.01 and settles the fallback choice.

Latency was measured end to end from a residential connection in Mexico to us-east-1, one request at a time per model, with up to 6 runs in parallel. It includes uploading 0.3–0.5 MB JPEGs. From inside AWS, expect lower latency, and less of a gain from downscaling.

**Confusion counts (TP/FP/FN/TN) for the fields that drive alerts.** These are for the recommended run, nova-2-lite +v2:
- `package_visible` 11/0/0/41. `person_present` 23/0/0/31. `phone_screen_shown` 5/0/0/49.

**Every error from every run**, so the percentages can be read in context:
- **`phone_screen_shown` on phones held back-to-camera** is the main weakness. Under the base prompt, every model says `true` whenever someone holds a phone: Nova Lite and Nova Pro got 4/4 wrong, Nova 2 Lite got 2–3/4 wrong. Prompt v2 fixes it for Nova 2 Lite (0/4 wrong at both sizes), halves it for Nova Pro, and does nothing for Nova Lite.
- **`package_visible` when the parcel is in someone's hands.** Nova Lite answers "visible" while the courier is still holding the box (place_01, place_03, carry_01_ir). Prompt v2 fixes this for Nova Lite. Nova Pro misses one box that rests on the mat while the courier's hands are still on it (place_02).
- **Downscaling to 768 px costs a little accuracy.** Nova 2 Lite called an empty doormat a package (box_04), in both of its 768 runs. Nova Lite misread a box held in the doorway as resting on the floor and not carried (place_03).
- **Determinism.** Two runs of Nova 2 Lite at temperature 0 differed on 1 field of 1 frame (phone_04). Nova Lite was bit-identical across runs. The k-of-n porch tracker should absorb flips like this.
- **JSON.** No parse failures in 594 calls. Nova 2 Lite always wraps its JSON in a ```` ```json ```` fence. The regex in `vision._parse` handles the fence, so do not tighten that regex.

## Recommended prompt (v2)

Same JSON contract as `core/src/doorledger/vision.py`, so `label_from_json` is unchanged. Only the field definitions are sharpened, and one line is added at the end. **I have not edited `core/`.** To adopt it, replace `PROMPT` with:

```text
You are the perception module of a home-care verification system watching a front-door camera.
Describe ONLY what is visible in the image. Answer with a single JSON object and nothing else:
{
  "package_visible": bool,          // a parcel/box/bag/envelope/cooler RESTING on the floor, mat or step. false if every parcel is in someone's hands
  "person_present": bool,           // any person visible near the door, including partly visible or seen from behind
  "person_carrying_package": bool,  // a person is holding a parcel/box/delivery bag in their hands or arms (not a purse or backpack)
  "vehicle_present": bool,          // a car/van/truck visible in the driveway or street close to the house
  "phone_screen_shown": bool,       // the lit DISPLAY of a phone faces the camera (you can see the screen content). false if you only see the back/camera side of a phone
  "confidence": number,             // 0..1, your overall confidence
  "note": string                    // <= 12 words, plain description
}
Doorbell cameras are wide-angle: objects near the edges look stretched. Small devices, pucks or doormats are not parcels.
```

How much v2 changed each model (mean accuracy over 5 fields, 54 frames):
- Nova 2 Lite: 99.3% → 100% (phone 96% → 100%). Cost +8%: about 80 more input tokens.
- Nova Pro: 98.1% → 98.9% (phone 93% → 96%).
- Nova Lite at 768 (extra run): 97.8% → 98.1% (package 98% → 100%, but phone 93% → 91%).

## Cost reality check (worth reading before the demo pitch)

At 1 frame every 1–2 s, a 30-minute expected window means 900–1,800 frames:
- Nova 2 Lite +v2: **$0.33–0.67 per window**. One hour of windows a day comes to about **$20–40 per patient per month**.
- Nova Lite at 768: $0.09–0.19 per window, about $6–12 per patient per month.

Levers, from cheapest to try onward:
1. Classify only on motion or change (Ring motion events, or frame differencing), not on a fixed clock.
2. Sample every 3–5 s once the porch state is stable.
3. Run the cheap Nova Lite at 768 by default, and escalate to Nova 2 Lite only when the frame is ambiguous or a person is present.
4. Shorten the output. Output tokens are about 52% of Nova 2 Lite's cost, so dropping or shortening `note` would help.

## Claude access (blocked on this account, so no measurements)

| Model id | Error |
|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` (also `global.`) | ResourceNotFound: *"Model use case details have not been submitted for this account"* |
| `us.anthropic.claude-sonnet-4-6` | Same error on image calls. A tiny text call succeeded once, then the image run failed on all 46 frames |
| `us.anthropic.claude-haiku-5-5`, `us.anthropic.claude-sonnet-5-5` (also `global.`) | AccessDenied: *"not available for this account"* |

**To unblock:** Brandon submits the one-time Anthropic use-case form in the Bedrock console (Model catalog → any Anthropic model). Haiku 5.5 and Sonnet 5.5 may also need account maturity or an AWS Sales request. Once unblocked, run `run_eval.py --runs haiku-4.5,haiku-5.5,sonnet-5.5,haiku-5.5+v2`. Those configs are already defined.

Cost estimates if unblocked. None of these are measured:
- Claude bills an image at roughly w·h/750 tokens after downscaling to ≤1.15 MP, so a 1536² frame is about 1,500 tokens.
- Haiku 5.5 ($0.11 / $0.55): about $0.21 per 1,000 frames.
- Haiku 4.5 ($1.10 / $5.50): about $2.10 per 1,000 frames.
- Sonnet 5.5 ($2.20 / $11): about $4.20 per 1,000 frames.

**Code gotcha for later:** per Anthropic's model docs, Haiku 5.5 and Sonnet 5.5 return 400 on a non-default `temperature`, and both think by default. `BedrockVision.classify` always sends `temperature: 0`, so it needs per-model inference settings before it can switch to them. `run_eval.py` already handles this: it omits temperature and sends `thinking: disabled` for Haiku 5.5 and `between_tools` for Sonnet 5.5.

## How the test set was built (and why you should not over-trust 100%)

- **Generator.** First choice was Amazon Nova Canvas, which this account rejects: *"marked by provider as Legacy and you have not been actively using the model in the last 30 days"*. I used **Stability Stable Image Core** (us-west-2, $0.04/image) instead.
- **Counts.** 44 generated frames, plus 4 PIL composites, plus 6 night-IR variants made with PIL, for **54 frames**.
- **Ring-like post-processing.** Each frame was resized to a Ring resolution (1536² or 1920×1080), given mild barrel distortion, and JPEG-compressed at q78.
- **Labels were fixed by eye from the contact sheet** (`contact_sheet.png`). The `fix_notes` field in `labels.json` records each fix. The generator often ignored the prompt:
  - 7 of 20 "package" prompts produced **no package**. It tends to draw a doorbell-like puck instead.
  - "Placing a box" and "picking up" scenes mostly show the box in hand, not on the floor.
  - One "elder picking up" frame shows him empty-handed.
  - "Walking away" scenes mostly show people walking *toward* the door.
  - Ground truth follows the image, not the prompt.
- **Phone screens are composites.** Stable Image Core drew all 4 caregivers holding the phone **back toward the camera**. Those 4 frames are kept as hard negatives (`phone_screen_shown=false`). The 5 positives are lit screens with a 6-digit code pasted on with PIL. They are much cleaner and more obvious than a real phone filmed at 30–50 cm through a fisheye lens, so the 100% recall on phone screens is optimistic.
- **Ambiguous fields are not scored.** 6 fields, listed in the `ambiguous` field of `labels.json`. Two of them (`vehicle_present` on away_02 and neg_shadow: distant cars across or down the street) I missed on the first pass and only found after the models flagged them. I marked them ambiguous rather than "correct for the model" because "close to the house" is a judgment call. Before that change, Nova Lite and Nova 2 Lite had one vehicle false positive each.
- **Class balance (after fixes).**
  - `package_visible`: 11 positive, 41 negative.
  - `person_present`: 23 / 31.
  - `person_carrying_package`: 9 / 43.
  - `vehicle_present`: **only 3 / 49**.
  - `phone_screen_shown`: 5 / 49.
  - Lighting: 36 day, 12 dusk, 6 night IR.
  - With n=54, one error moves a field's accuracy about 2 points. **Nova 2 Lite, Nova 2 Lite +v2 and Nova Pro are statistically tied.** The clear separations are Nova Lite's held-package false positives, and back-facing phones under the base prompt.

### Honest caveats

1. **Synthetic is not Ring footage.** The images are clean, well lit, centred and high-detail. Real Ring frames have motion blur, H.264 macroblocking, IR bloom, raindrops, sun glare, the Ring watermark, and real fisheye stretch at the frame edges. Night IR here is just a grayscale filter. **Re-validate on Ring Playground streams (spike S1/S2) before locking the model.** The pipeline is ready: drop real frames into `images/`, label them in `labels.json`, and rerun.
2. **Small n, near ceiling.** Accuracy is saturated, so this set picks a *tier*, not a winner among the top three. Harder real frames will spread them out.
3. **Throttling.** A brand-new account got ThrottlingException from Stable Image Core almost immediately, and once from Nova 2 Lite with 6 parallel runs. The evaluator retries throttled calls, so latency figures exclude the back-off. Production at 1 frame/s is 60 requests per minute per camera, so **check the Nova 2 Lite RPM/TPM quotas** in the Service Quotas console. `doorledger-dev` is not allowed to read quotas.
4. **`vehicle_present` is barely tested** (3 positives). Its definition ("close to the house") is fuzzy, as both missed labels showed.
5. **Latency is from a laptop, not from AWS.** In-region compute should do better on p50, and likely on the 768-vs-full gap too.

## Spend

| Item | US$ |
|---|---|
| Stable Image Core: 1 probe + 44 test images | 1.80 |
| Converse probes (one image per model) | ~0.004 |
| `run_eval.py`: 11 runs × 54 frames (594 calls, recorded token usage × price list) | 0.39 |
| Nova Canvas / Claude calls | 0 (rejected) |
| **Total (estimated)** | **≈ $2.19** (budget $3) |

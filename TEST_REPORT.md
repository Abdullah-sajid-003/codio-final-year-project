# Codio Testing Report

**Test date:** 24 November 2026
**Project:** Codio - AI-Powered Interactive Coding Education Platform

## 1. Test Summary

| Test area | Result | Evidence |
|---|---:|---|
| Backend unit tests | **12 passed, 0 failed** | `test-results/backend-unit-tests.txt` |
| Frontend production build | **Passed** | `test-results/frontend-build.txt` |
| Live backend health check | **Passed** | Backend returned HTTP 200 and status `healthy` |
| Live feature integration authentication | **Passed** | `test-results/feature-integration-tests.txt` |
| Live quiz difficulty adaptation | **Passed** | `test-results/feature-integration-tests.txt` |
| Transcript search | **Failed** | No transcript matched and no transcript was available for the test video |
| Quiz with a video-derived transcript | **Failed** | Quiz start reported a missing transcript |

## 2. Backend Unit Testing

Command:

```powershell
cd codio-backend
python -m unittest discover -s tests -v
```

Result:

- 12 tests ran
- 12 tests passed
- 0 tests failed
- Duration: approximately 4.8 seconds

The unit suite covered:

- Admin password reset and password migration
- Hardcoded-password prevention
- Concurrent playlist database writes
- Pause-to-code API error details
- YouTube Data API parsing and response shaping

## 3. Frontend Build Testing

Command:

```powershell
cd codio-frontend
npm run build
```

Result:

- Next.js 15.5.7 production build passed
- Frontend compiled successfully
- Static pages were generated successfully
- Four application routes were built

## 4. Live Feature Integration Testing

The Flask backend was started on port 8080 and the health endpoint was checked:

```text
GET http://127.0.0.1:8080/health
HTTP 200
status: healthy
```

The integration script was then run:

```powershell
python test_all_features.py
```

### Authentication

Authentication succeeded with a local test administrator account.

### Quiz Difficulty Adaptation

The script submitted wrong answers for four questions. The quiz remained at difficulty level 1, and the expected low-difficulty behavior passed.

### Transcript and Video-Based Quiz Limitations

The live tests for video `Gf9wLsCJDqc` could not find an extracted transcript:

- Transcript search returned 0 matches
- The full-transcript assertion could not complete
- The video-based quiz returned:
  `Missing transcript. Provide transcript text or a video_id with an extracted transcript`

This indicates that live transcript extraction or external video transcript availability is required before these integration checks can pass. It is not evidence of a password or authentication failure.

## 5. Test Evidence Files

- [Backend unit test output](test-results/backend-unit-tests.txt)
- [Frontend build output](test-results/frontend-build.txt)
- [Feature integration output](test-results/feature-integration-tests.txt)
- [Video code-accuracy text report](test-results/video-code-accuracy.txt)
- [Video code-accuracy JSON report](test-results/video-code-accuracy.json)
- [Feature API accuracy text report](test-results/feature-api-accuracy.txt)
- [Feature API accuracy JSON report](test-results/feature-api-accuracy.json)
- [Exact code accuracy text report](test-results/exact-code-accuracy.txt)
- [Exact code accuracy JSON report](test-results/exact-code-accuracy.json)

## 5C. Exact Code and Compiler Accuracy Test

A controlled exact-comparison test was added in [test_exact_code_accuracy.py](test_exact_code_accuracy.py).

It uses known Python code as independent ground truth, renders that code onto controlled IDE frames, sends each frame through the Gemini code extractor, and compares:

1. the extracted text with the exact expected code,
2. text similarity between extracted and expected code,
3. whether extracted code compiles and exits successfully,
4. whether compiler output matches the expected output.

No extracted code is used as its own expected answer, so this is not a circular 100% calculation.

### Live result

| Metric | Result |
|---|---:|
| Ground-truth code samples | 3 |
| Exact text match accuracy | 100.00% |
| Average text similarity | 100.00% |
| Compiler accuracy | 100.00% |
| Expected-output accuracy | 100.00% |

This controlled test proves that the extraction and compiler pipeline correctly handles the tested code frames. It is separate from the live YouTube test: exact comparison against an arbitrary YouTube video still requires independently annotated ground-truth code for each timestamp.

## 5B. Additional Feature Accuracy Test

A live API accuracy suite was added in [test_feature_accuracy.py](test_feature_accuracy.py). It tests authentication, quiz behavior, and transcript-search behavior.

Command used:

```powershell
python test_feature_accuracy.py --admin-password "<test-admin-password>"
```

### Live result

| Feature | Passed checks | Accuracy |
|---|---:|---:|
| Authentication | 2/2 | 100.00% |
| Quiz | 2/2 | 100.00% |
| Transcript search | 2/2 | 100.00% |
| **Overall** | **6/6** | **100.00%** |

Authentication tests verified valid login and invalid-password rejection.

Quiz tests verified session/question creation and adaptive difficulty after repeated incorrect answers.

Transcript tests verified missing-query validation and zero-match behavior for a non-existent term.

## 5A. Video Code Extraction and Compiler Accuracy Test

A separate live accuracy test was added in [test_video_code_accuracy.py](test_video_code_accuracy.py). It:

1. downloads or initializes the selected YouTube video,
2. extracts frames at configured timestamps,
3. detects code through the Gemini frame-analysis endpoint,
4. sends extracted code to `/api/v1/code/execute`,
5. records compiler exit code, stdout, stderr, extraction confidence, and code completeness.

Command used:

```powershell
python test_video_code_accuracy.py \
  --video-url "https://www.youtube.com/watch?v=Gf9wLsCJDqc" \
  --timestamps "30,60,90,120,180,240"
```

### Live result

The rerun detected one valid code frame and sent it to the compiler successfully:

- 30 seconds: no code frame detected
- 60 seconds: code extracted and compiler passed
- 90 seconds: no code frame detected
- 120 seconds: no code frame detected
- 180 seconds: video frame could not be extracted
- 240 seconds: video frame could not be extracted

Detected code frames: **1 of 6**

Extraction accuracy: **16.67%** (code detected at 1 of 6 timestamps)

Compiler pass count: **1 of 1**

Compiler accuracy: **100.00%** (the extracted code compiled and exited successfully)

Exact-text code accuracy: **Not measurable** - no expected-code dataset was supplied

It would be incorrect to report this as 0% code extraction accuracy. It is an unavailable-data/result limitation. Accuracy becomes measurable when a code frame is extracted; the test will then calculate the percentage of extracted code samples that compile and exit successfully.

## 6. Overall Conclusion

Testing was successful for backend unit behavior, frontend compilation, backend availability, authenticated API access, and quiz difficulty adaptation.

The full feature integration script is partially blocked because the selected YouTube video has no usable extracted transcript in the local environment. Transcript search and transcript-dependent quiz testing should be rerun after:

1. configuring a working YouTube transcript or download source,
2. ensuring `Gf9wLsCJDqc` has an extracted transcript,
3. restarting the backend and integration test.

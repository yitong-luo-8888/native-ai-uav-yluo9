# HW7 — Understanding the pipeline

Answer each question in your own words, from your own `hw07/clues/` code.
For every answer, name the file (and line) you are describing.
One of these questions will be drawn from a hat during your presentation
on Oct. 15, and you will answer it live.

## Data and structure

### Q1. Data in, data out

What is a `Candidate`, and what is a `ClueAssessment`? Where does each come from, and where does each go (name the file or MQTT topic)?

**Answer:**


### Q2. Stages and their specs

Where is each stage defined in your code, and what does its `StageSpec` hold? If you renamed a stage, which files would change?

**Answer:**


### Q3. What each stage sees

For each of your three stages, list what goes into the request (images, text). Why must Describe never see the missing person's description?

**Answer:**


### Q4. Schemas

What does "schema" mean for a stage, and what is a Pydantic class? What happens in your code if the model returns `relevance = "maybe"`?

**Answer:**


### Q5. The contract

What does `contract.py` fix that you may not change, and why does it exist? Which of its classes does your code create, and which does it only receive?

**Answer:**


### Q6. Dependencies

Which of your files import which? Why does your `llm.py` not import `Description`, `Relevance` or `ClueDecision`?

**Answer:**


## Calling Claude

### Q7. One call, end to end

Trace one Describe call from `evaluate.py` to `client.beta.messages.parse(...)`, listing each function and its file. Where are the prompt and the effort chosen?

**Answer:**


### Q8. System prompt and user message

In your requests, what goes in the system prompt and what goes in the user message? Why is that split useful?

**Answer:**


### Q9. Images

How is the crop sent to Claude: what is in an image content block? What is `ground_m_per_px` for, and why is the crop upscaled before it is sent?

**Answer:**


### Q10. Effort, cost and the key

What does effort control, which effort did you give each stage, and why? How is the cost of a call calculated? Where does your code get the API key, and how do you make sure it is never committed?

**Answer:**


### Q11. When a call fails

Walk through what your code does if Claude refuses, cuts off, or returns an answer that doesn't fit the schema. What does the planner receive in each case?

**Answer:**


## Control and safety

### Q12. The closer look

What two things can trigger a closer look? What stops it from happening twice? What happens in flight, where `closer_look` is `None`?

**Answer:**


### Q13. The model's authority

Which decisions does the model make, and which does your code make? Why does the converge-search centre come from code, and what can your validator still reject?

**Answer:**


### Q14. Prompts versus code

You want Relevance to also consider the clue's distance from the last known point. Is that a prompt change, a code change, or both? Which files?

**Answer:**


## Testing and evaluation

### Q15. Testing without Claude

How does `FakeBackend` let you test a stage without an API key? Name one thing your unit tests can prove and one thing only `evaluate.py` can show.

**Answer:**


### Q16. Measuring

How does `evaluate.py` decide whether a clue was handled correctly? Why run each clue three times, and what would 60% agreement tell you?

**Answer:**


### Q17. Scale

Why are the clue icons drawn about 9 times life size in the simulator, and what does `scene_scale` correct? What went wrong for the cardigan without it?

**Answer:**


### Q18. Using the trace

How did you use the trace from `evaluate.py` to find the first stage whose answer was wrong in your traced failure?

**Answer:**


## Running end to end (Part 2)

### Q19. The running system

List every process that must be running for your end-to-end demo in new-gui and what each one does. Which MQTT topics connect them?

**Answer:**


### Q20. Threads in the detector

Why does `detector.py` run the LLM calls on a separate thread with a queue instead of inside the frame handler?

**Answer:**

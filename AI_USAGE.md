# AI Tool Usage

## Tools I Used
- Claude (Anthropic) — used throughout the development process for architecture discussion, code generation and debugging

---

## What Helped Most

**1. Architecture validation**
I used Claude to validate and stress-test my architectural decisions — specifically around the separation of concerns between the Upload API and the Worker processing pipeline, and the choice of Redis as a queue mechanism vs other options. The discussion helped confirm that my approach aligned with industry standards for async file processing systems.

**2. Boilerplate code generation**
Claude generated initial versions of the step files (validate, transform, convert, compress, notify) and the database operations in dbops.py, saving significant time on repetitive code.

---

## What I Had to Fix

**1. Incorrect function signatures**
Claude generated step functions with inconsistent signatures — `validate_file` accepted 2 arguments but the worker called it with 3. I caught this from the error logs and fixed the worker to handle validate differently from other steps.

**2. Output file extension problem**
Claude used `.out` as a generic output file extension for all steps. I identified that this would break the next step since it couldn't determine the file type from the extension. I redesigned the output file naming to use the correct extension per step.

**3. Wrong WORKDIR in Dockerfile**
Claude set `WORKDIR /app` but then used `COPY . .` which copied the `app/` folder into `/app/` creating `/app/app/`. I caught this from the error logs and fixed the Dockerfile to use `COPY app/ .` instead.

**4. run_id naming**
Claude named the step attempt counter `run_id` which was ambiguous — it could mean a run of the whole job. I renamed it to `attempt_number` to make it clear it tracks attempts of a specific step.

**5. Combining validate and transform steps**
Claude initially suggested combining content validation into the transform step to avoid double file reads. I questioned this since it would blur the responsibility of each step and make the code harder to understand. We kept them separate and accepted the trade-off of multiple reads.

**6. Parallel step execution misconception**
Claude initially suggested implementing parallel step execution as a Nice to Have. I pointed out that all pipeline steps are sequential by nature — each step depends on the previous step's output. There are no independent steps that could safely run in parallel. Parallel processing is only applicable at the job level (multiple workers handling different jobs simultaneously).

**7. Non-streamable operations**
I identified that certain operations cannot be streamed regardless of the approach — specifically nested JSON to CSV conversion which requires the full JSON structure in memory to flatten it. Claude initially presented streaming as universally applicable. I pushed back and we documented the specific cases where streaming is not possible and why.

---

## What AI Struggled With

**Streaming strategy**
Claude initially suggested loading entire files into memory for JSON validation (`json.load()`). I had to push back and we settled on using `ijson` for streaming JSON validation. Claude also initially missed the distinction between streaming at the upload level vs streaming at the processing level.

**Swagger UI limitations**
Claude did not flag known Swagger UI limitations that affected the user experience — specifically around file downloads. I discovered these limitations during manual testing and documented workarounds in the README.

**Database schema evolution**
When I added new columns to the tables (e.g. `attempt_number`, `progress`, `estimated_seconds`), Claude updated the `CREATE TABLE IF NOT EXISTS` statements in `dbops.py` but missed that existing tables in PostgreSQL would not be affected — `CREATE TABLE IF NOT EXISTS` skips creation entirely if the table already exists. I had to manually drop the tables in pgAdmin and restart the containers each time a schema change was made.

I also suggested that both `main.py` and `worker.py` should independently call `init_db()` on startup — rather than depending on one or the other to create the tables first. My reasoning was that in our architecture each module (API and Worker) should be self-sufficient. This way if you stop the worker and restart it without touching `main.py`, the worker will still ensure the tables exist on its own startup.

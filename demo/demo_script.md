# Demo script (2–3 minutes)

Default content (CLAUDE.md §15 Q2, confirm): Startup Pitch · Normal · VC + Student + **one custom persona typed live on stage** · curveball `slides_down`.

1. **Hook (15 s):** "Practising slides isn't the same as practising your audience — or the things that go wrong."
2. **Setup (20 s):** pick Startup Pitch, type a custom persona ("my co-founder's skeptical mother"), drop the sample PDF, Start. Three clicks plus one sentence.
3. **Live claim (20 s):** "We can acquire 100,000 users in six months."
4. **VC interruption (20 s):** "What evidence supports that projection?"
5. **Answer (15 s):** "We plan to grow through university communities."
6. **Follow-up (15 s):** "What early data supports that channel?" — brief answer.
7. **Curveball (30 s):** slides go black — moderator: "Sorry, projector's down — can you keep going?" Presenter continues from memory. Slides restore.
8. **Q&A (15 s):** the custom persona asks one question in character.
9. **Report (25 s):** the weak growth claim with its quote, the VC exchange, the Recovery card ("resumed in X s"), pace/fillers if measured.
10. **Close (10 s):** "The first time you face a tough question — or a dead projector — shouldn't be when it matters most."

Rehearse with the debug `/api/sessions/{id}/curveball` endpoint; in the live demo let the scheduler fire it, and keep the debug trigger as the fallback if timing is off. Never present pre-scripted AI responses as live. If we demo from the backup recording, we say so.

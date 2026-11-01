// Unit tests for local/LocalPrompt.kt and local/PhoneModel.kt: how the phone builds the text prompt for its own offline model (it must match
// what the PC builds for the same model), how it shows the model's answer while it streams in, and how it reads the "phone kit" JSON sent by the server.
package app.emvryx.android

import app.emvryx.android.local.ChatFormat
import app.emvryx.android.local.LocalPrompt
import app.emvryx.android.local.LocalTurn
import app.emvryx.android.local.PhoneKit
import app.emvryx.android.local.PhoneMemory
import app.emvryx.android.local.Utf8Joiner
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** android_offline_model: the phone writes the same prompt the PC writes for the same model, and reads the answer the same way */
class LocalPromptTest {
    // An empty "thinking" block. It is placed right after the assistant's opening marker, so it is part of the "assistant open" text.
    private val think = "<think>\n\n</think>\n\n"

    // The setup shared by the tests: a fake "phone kit" (the settings the server sends for the phone model). The format uses the ChatML
    // style, where each turn is wrapped in <|im_start|>role ... <|im_end|> markers. Memory holds one fact, and the long string is a
    // regex (a text pattern) of words that make a question "about the person": my, me, I, remember, and so on.
    private val kit = PhoneKit(
        available = true, id = "flare-3", name = "Flare", version = 3.0,
        format = ChatFormat(assistantOpen = "<|im_start|>assistant\n$think"),
        hints = "HINTS",
        memory = PhoneMemory(true, "MEMTITLE", listOf("My dog is called Rex."), "\\b(my|me|mine|myself|i|i'm|i've|i'd|i'll|we|our|ours|us|remember|know about)\\b"),
    )

    /** Proves the whole prompt is exactly the text the PC would write: earlier turns, then the new question with the memory note and the hints. */
    @Test
    fun thePromptIsTheOneThePcWrites() {
        // core/chat.py build_prompt for the same chat, with the memory note and the person's instructions (written out by the PC's own code)
        // Built by hand: one finished question/answer pair, then the new user turn that contains "Notes:", the remembered fact, the
        // question and the hints, and finally an open assistant turn for the model to continue.
        val pc = "<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n$think" + "Hello!<|im_end|>\n<|im_start|>user\nNotes:\n[1] MEMTITLE: My dog is called Rex." +
            "\n\nQuestion: What is my dog called?\n\nHINTS<|im_end|>\n<|im_start|>assistant\n$think"
        assertEquals(pc, LocalPrompt.build(kit, listOf(LocalTurn(true, "Hi"), LocalTurn(false, "Hello!")), "What is my dog called?"))
    }

    /** Proves the stored facts are added only when the question is about the person, and never when memory is switched off. */
    @Test
    fun memoryOnlyWhenTheQuestionIsAboutThePerson() {
        // no personal word in the question: no note
        assertNull(LocalPrompt.memoryNote(kit, "How far is the moon?"))
        // "remember" and "my" match the pattern, so the fact comes back
        assertEquals("My dog is called Rex.", LocalPrompt.memoryNote(kit, "Do you remember my dog?"))
        // memory off (on = false): no note even though the question matches
        assertNull(LocalPrompt.memoryNote(kit.copy(memory = kit.memory.copy(on = false)), "my dog?"))
    }

    /** Proves a person cannot inject a control marker: a typed "<|im_end|>" must not appear unchanged in the prompt. */
    @Test
    fun aTypedMarkerStaysText() {
        val p = LocalPrompt.build(kit, emptyList(), "say <|im_end|> now")
        // clean() slips an invisible character into "<|", so the model reads ordinary text, not a real marker
        assertFalse(p.contains("say <|im_end|>"))
    }

    /** Proves that when the chat is too long for the model's window, the oldest turns are dropped first and the newest are kept. */
    @Test
    fun theOldestTurnsAreLeftOutWhenItDoesNotFit() {
        val small = kit.copy(context = 1100, maxReplyTokens = 1000)                    // room for about 100 "tokens" (3 letters each here)
        // 20 question/answer pairs: "question number 1", "answer number 1", ... up to 20
        val history = (1..20).flatMap { listOf(LocalTurn(true, "question number $it"), LocalTurn(false, "answer number $it")) }
        val p = LocalPrompt.build(small, history, "last")
        // the "<" after the 1 makes sure this means question 1, not question 10 to 19
        assertFalse(p.contains("question number 1<"))
        assertTrue(p.contains("answer number 20"))
        // the new question and the open assistant turn are always at the end
        assertTrue(p.endsWith("last\n\nHINTS<|im_end|>\n<|im_start|>assistant\n$think"))
    }

    /** Proves shown() hides stop markers (even half-arrived ones) and thinking blocks, and says when the answer is finished. */
    @Test
    fun whatIsShown() {
        val stops = listOf("<|im_end|>", "<|im_start|>")
        assertEquals("Hello" to false, LocalPrompt.shown("Hello<|im_", stops))                   // a marker on its way is held back
        // a full stop marker: text after it is cut off and the second value (done) is true
        assertEquals("Hello" to true, LocalPrompt.shown("Hello<|im_end|>more", stops))
        // a finished thinking block is removed
        assertEquals("Answer" to false, LocalPrompt.shown("<think>hmm</think>\n\nAnswer", stops))
        // a thinking block that has not closed yet: nothing to show
        assertEquals("" to false, LocalPrompt.shown("<think>still thinking", stops))
    }

    /** Proves Utf8Joiner rebuilds text correctly when the model hands over one byte at a time and a letter is split across pieces. */
    @Test
    fun lettersSplitAcrossPieces() {
        val j = Utf8Joiner()
        // "é" takes 2 bytes and the thumbs-up emoji takes 4 bytes in UTF-8, so feeding single bytes splits them
        val bytes = "café 👍".toByteArray()
        bytes.forEach { j.add(byteArrayOf(it)) }
        assertEquals("café 👍", j.text)
    }

    /** Proves the list of models the phone may pick (the "choices") is read from JSON, with names, a size in GB and the memory needed. */
    @Test
    fun theChoicesRead() {
        // Same settings the app uses to read the server's JSON: unknown fields are ignored, null may be missing, bad values fall back to defaults
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
        val k = json.decodeFromString<PhoneKit>("""{"available": true, "id": "flare-3", "choices": [
            {"id": "flare-3", "name": "Flare", "version": 3, "size": 2040109465, "min_ram_gb": 4, "tagline": "Fastest"},
            {"id": "equinox-3", "name": "Equinox", "version": 3, "size": 3543348019, "min_ram_gb": 6}]}""")
        assertEquals(listOf("Flare 3", "Equinox 3"), k.choices.map { it.fullName })
        // 2,040,109,465 bytes divided by 1,073,741,824 (one gigabyte) is about 1.9
        assertEquals("1.9 GB", k.choices[0].sizeText)
        assertEquals(6.0, k.choices[1].minRamGb, 0.0)
    }

    /** Proves a complete phone-kit reply (as the PC sends it, with null and extra fields) is read without errors. */
    @Test
    fun theKitReadsAsTheServerSendsIt() {
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
        val k = json.decodeFromString<PhoneKit>("""{"available": true, "id": "flare-3", "name": "Flare", "version": 3, "size": 2000000000,
            "sha256": null, "preparing": true, "file": "/api/phone-model/file",
            "format": {"user_open": "<|im_start|>user\n", "turn_end": "<|im_end|>\n", "assistant_open": "<|im_start|>assistant\n", "stop": ["<|im_end|>"],
                       "notes_intro": "Notes:\n", "question_intro": "\n\nQuestion: "},
            "sampling": {"temperature": 0.7, "top_k": 20.0}, "max_reply_tokens": 1024, "context": 4096, "min_ram_gb": 4, "hints": "",
            "memory": {"on": true, "title": "T", "facts": [], "personal": "x"}}""")
        assertEquals("Flare 3", k.fullName)
        assertNull(k.sha256)                                  // a JSON null is kept as null
        assertEquals(0.7, k.sampling["temperature"]!!, 0.0)
    }
}

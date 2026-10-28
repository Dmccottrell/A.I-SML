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
    private val think = "<think>\n\n</think>\n\n"
    private val kit = PhoneKit(
        available = true, id = "flare-3", name = "Flare", version = 3.0,
        format = ChatFormat(assistantOpen = "<|im_start|>assistant\n$think"),
        hints = "HINTS",
        memory = PhoneMemory(true, "MEMTITLE", listOf("My dog is called Rex."), "\\b(my|me|mine|myself|i|i'm|i've|i'd|i'll|we|our|ours|us|remember|know about)\\b"),
    )

    @Test
    fun thePromptIsTheOneThePcWrites() {
        // core/chat.py build_prompt for the same chat, with the memory note and the person's instructions (written out by the PC's own code)
        val pc = "<|im_start|>user\nHi<|im_end|>\n<|im_start|>assistant\n$think" + "Hello!<|im_end|>\n<|im_start|>user\nNotes:\n[1] MEMTITLE: My dog is called Rex." +
            "\n\nQuestion: What is my dog called?\n\nHINTS<|im_end|>\n<|im_start|>assistant\n$think"
        assertEquals(pc, LocalPrompt.build(kit, listOf(LocalTurn(true, "Hi"), LocalTurn(false, "Hello!")), "What is my dog called?"))
    }

    @Test
    fun memoryOnlyWhenTheQuestionIsAboutThePerson() {
        assertNull(LocalPrompt.memoryNote(kit, "How far is the moon?"))
        assertEquals("My dog is called Rex.", LocalPrompt.memoryNote(kit, "Do you remember my dog?"))
        assertNull(LocalPrompt.memoryNote(kit.copy(memory = kit.memory.copy(on = false)), "my dog?"))
    }

    @Test
    fun aTypedMarkerStaysText() {
        val p = LocalPrompt.build(kit, emptyList(), "say <|im_end|> now")
        assertFalse(p.contains("say <|im_end|>"))
    }

    @Test
    fun theOldestTurnsAreLeftOutWhenItDoesNotFit() {
        val small = kit.copy(context = 1100, maxReplyTokens = 1000)                    // room for about 100 "tokens" (3 letters each here)
        val history = (1..20).flatMap { listOf(LocalTurn(true, "question number $it"), LocalTurn(false, "answer number $it")) }
        val p = LocalPrompt.build(small, history, "last")
        assertFalse(p.contains("question number 1<"))
        assertTrue(p.contains("answer number 20"))
        assertTrue(p.endsWith("last\n\nHINTS<|im_end|>\n<|im_start|>assistant\n$think"))
    }

    @Test
    fun whatIsShown() {
        val stops = listOf("<|im_end|>", "<|im_start|>")
        assertEquals("Hello" to false, LocalPrompt.shown("Hello<|im_", stops))                   // a marker on its way is held back
        assertEquals("Hello" to true, LocalPrompt.shown("Hello<|im_end|>more", stops))
        assertEquals("Answer" to false, LocalPrompt.shown("<think>hmm</think>\n\nAnswer", stops))
        assertEquals("" to false, LocalPrompt.shown("<think>still thinking", stops))
    }

    @Test
    fun lettersSplitAcrossPieces() {
        val j = Utf8Joiner()
        val bytes = "café 👍".toByteArray()
        bytes.forEach { j.add(byteArrayOf(it)) }
        assertEquals("café 👍", j.text)
    }

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
        assertNull(k.sha256)
        assertEquals(0.7, k.sampling["temperature"]!!, 0.0)
    }
}

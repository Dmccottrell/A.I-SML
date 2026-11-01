// Unit tests for local/PhoneVision.kt (the Vision helper object): the offline "picture model" on the phone. These check how the question is put
// into the PC's instructions, how what the picture shows is added to the chat message, and how the PC's download details ("kit") are read.
package app.emvryx.android

import app.emvryx.android.local.Vision
import app.emvryx.android.local.VisionKit
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** android_phone_vision: the picture model on the phone gets the PC's instructions, and the chat model gets what it saw */
class PhoneVisionTest {
    /** Proves Vision.prompt() swaps the {question} placeholder in the PC's instruction text with the (trimmed) question, or a default question. */
    @Test
    fun theQuestionGoesIntoThePcsInstructions() {
        // A template is a text with a gap in it. The PC sends one; "{question}" is the gap where the person's question goes.
        val t = "Look carefully. The person who sent it asks: \"{question}\". Do not answer that yourself."
        // the spaces around the question are trimmed before it goes in
        assertEquals("Look carefully. The person who sent it asks: \"Is this bill right?\". Do not answer that yourself.", Vision.prompt(t, " Is this bill right? "))
        // no question typed: a default one is used
        assertTrue(Vision.prompt(t, "").contains("What is in this picture?"))
    }

    /** Proves withPicture() builds the chat message: the question, a label line, then what the picture showed; and it has a default question. */
    @Test
    fun whatItSawGoesAfterTheQuestion() {
        val m = Vision.withPicture("What breed is it?", "A brown dog on a sofa.")
        assertTrue(m.startsWith("What breed is it?\n\n[What the picture I sent shows, looked at on this phone:]\n"))
        assertTrue(m.endsWith("A brown dog on a sofa."))
        // an empty question gets the default "What is in this picture?..."
        assertTrue(Vision.withPicture("", "x").startsWith("What is in this picture?"))
    }

    /** Proves the PC's picture-model kit JSON is read: the two download parts (model and mmproj), their file addresses and the memory needed. */
    @Test
    fun thePcsKitIsRead() {
        // the shape of app/phone_model.py vision_kit
        // ignoreUnknownKeys lets the reply carry fields (like "size" for each part's checksum) that the app does not model
        val k = Json { ignoreUnknownKeys = true }.decodeFromString<VisionKit>("""{"available": true, "size": 420000, "preparing": false,
            "parts": {"model": {"size": 300000, "sha256": "ab", "file": "/api/phone-model/vision/file?part=model"},
                      "mmproj": {"size": 120000, "sha256": "cd", "file": "/api/phone-model/vision/file?part=mmproj"}},
            "prompt": "Look. {question}", "max_reply_tokens": 600, "min_ram_gb": 6}""")
        // both parts are present, in the order the app downloads them
        assertEquals(listOf("model", "mmproj"), Vision.PARTS.filter { it in k.parts })
        assertEquals("/api/phone-model/vision/file?part=mmproj", k.parts["mmproj"]!!.file)
        assertEquals(6.0, k.minRamGb, 0.0)
    }
}

package app.emvryx.android

import app.emvryx.android.local.Vision
import app.emvryx.android.local.VisionKit
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** android_phone_vision: the picture model on the phone gets the PC's instructions, and the chat model gets what it saw */
class PhoneVisionTest {
    @Test
    fun theQuestionGoesIntoThePcsInstructions() {
        val t = "Look carefully. The person who sent it asks: \"{question}\". Do not answer that yourself."
        assertEquals("Look carefully. The person who sent it asks: \"Is this bill right?\". Do not answer that yourself.", Vision.prompt(t, " Is this bill right? "))
        assertTrue(Vision.prompt(t, "").contains("What is in this picture?"))
    }

    @Test
    fun whatItSawGoesAfterTheQuestion() {
        val m = Vision.withPicture("What breed is it?", "A brown dog on a sofa.")
        assertTrue(m.startsWith("What breed is it?\n\n[What the picture I sent shows, looked at on this phone:]\n"))
        assertTrue(m.endsWith("A brown dog on a sofa."))
        assertTrue(Vision.withPicture("", "x").startsWith("What is in this picture?"))
    }

    @Test
    fun thePcsKitIsRead() {
        // the shape of app/phone_model.py vision_kit
        val k = Json { ignoreUnknownKeys = true }.decodeFromString<VisionKit>("""{"available": true, "size": 420000, "preparing": false,
            "parts": {"model": {"size": 300000, "sha256": "ab", "file": "/api/phone-model/vision/file?part=model"},
                      "mmproj": {"size": 120000, "sha256": "cd", "file": "/api/phone-model/vision/file?part=mmproj"}},
            "prompt": "Look. {question}", "max_reply_tokens": 600, "min_ram_gb": 6}""")
        assertEquals(listOf("model", "mmproj"), Vision.PARTS.filter { it in k.parts })
        assertEquals("/api/phone-model/vision/file?part=mmproj", k.parts["mmproj"]!!.file)
        assertEquals(6.0, k.minRamGb, 0.0)
    }
}

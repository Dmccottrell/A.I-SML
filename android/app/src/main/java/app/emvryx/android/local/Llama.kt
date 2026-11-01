// Llama.kt: the Kotlin side of the phone's own language model. llama.cpp is a C++ program that runs a model file;
// it is built into the app (src/main/cpp/emvryx_llama.cpp) and the `external` functions at the bottom are the doors into it
// (called JNI, the Java Native Interface, which lets Kotlin call C++ code). Callers: PhoneModel.kt and PhoneVision.kt.

package app.emvryx.android.local

/**
 * The phone's own copy of llama.cpp (src/main/cpp/emvryx_llama.cpp): loads the model file and writes answers token by token.
 * Every call blocks, so callers run it off the main thread; one answer at a time.
 * A "token" is a small piece of text (a word or part of one) that the model reads and writes.
 */
object Llama {
    /** Gives each piece of the answer (UTF-8 bytes); return false to stop. A `fun interface` is a one-method interface that can be written as a lambda. */
    fun interface Sink {
        fun piece(bytes: ByteArray): Boolean
    }

    /** Why an answer ended: finished by itself, hit the token limit, was stopped by the caller, the prompt did not fit in memory, or it failed. */
    enum class End { Finished, Length, Stopped, TooLong, Failed }

    // null = not tried yet, true = the C++ library loaded, false = it could not load.
    private var ready: Boolean? = null

    /** False on a phone the engine was not built for (it is built for 64-bit ARM phones, which is nearly all phones since 2017). The first answer is remembered. */
    // @Synchronized: only one thread at a time may run this, so the library is loaded once.
    @Synchronized
    fun available(libDir: String): Boolean {
        // Already tried: give the remembered answer.
        ready?.let { return it }
        ready = try {
            // Load the compiled C++ library (libemvryx_llama.so) and start it; any failure (even a missing-library Error) means "not available".
            System.loadLibrary("emvryx_llama")
            nativeInit(libDir)
            true
        } catch (e: Throwable) {
            false
        }
        return ready == true
    }

    /** A loaded model. [handle] is a number the C++ side uses to find it in memory (0 = freed). Only this file can make one (internal constructor); use [load]. */
    class Model internal constructor(private var handle: Long) {
        /** How many tokens [text] is. */
        fun count(text: String): Int = nativeCount(handle, text)

        /** Asks a running answer to stop as soon as it can. */
        fun stop() = nativeStop(handle)

        /**
         * Writes an answer to [prompt], at most [maxTokens] tokens, sending each piece to [sink]. [s] holds the sampling settings
         * (how adventurous the word choice is) by name; missing ones use the defaults below. Returns why it ended.
         */
        fun generate(prompt: String, maxTokens: Int, s: Map<String, Double>, sink: Sink): End {
            // temperature: higher = more random. top_k / top_p / min_p: cut off unlikely words. repeat_penalty / presence_penalty: discourage repeating.
            // The -1 is the random seed: negative means pick a different one each time.
            val r = nativeGenerate(
                handle, prompt, maxTokens,
                (s["temperature"] ?: 0.7).toFloat(), (s["top_k"] ?: 20.0).toInt(), (s["top_p"] ?: 0.8).toFloat(), (s["min_p"] ?: 0.0).toFloat(),
                (s["repeat_penalty"] ?: 1.0).toFloat(), (s["presence_penalty"] ?: 0.0).toFloat(), -1, sink,
            )
            // The C++ side answers with a number: 0 finished, 1 hit the length limit, 2 stopped by the caller, -1 prompt too long, anything else a failure.
            return when (r) {
                0 -> End.Finished
                1 -> End.Length
                2 -> End.Stopped
                -1 -> End.TooLong
                else -> End.Failed
            }
        }

        /** Frees the model's memory. Safe to call twice (the handle is zeroed after the first). */
        fun close() {
            if (handle != 0L) nativeFree(handle)
            handle = 0
        }
    }

    /**
     * android_phone_vision: looks at [image] (a JPEG or PNG) with the picture model and its reader ([mmproj], the part that turns pictures
     * into something the model understands), and writes what it shows. Loads them, answers, frees them: slow, but never held in memory.
     */
    fun describe(model: String, mmproj: String, image: ByteArray, prompt: String, maxTokens: Int, sink: Sink): End =
        when (nativeDescribe(model, mmproj, image, prompt, maxTokens, sink)) {
            0 -> End.Finished
            1 -> End.Length
            2 -> End.Stopped
            -1 -> End.TooLong
            else -> End.Failed
        }

    /** Loads the model (a few seconds); null when it cannot be (not enough memory, a damaged file) */
    fun load(path: String, context: Int): Model? = nativeLoad(path, context, 0).takeIf { it != 0L }?.let { Model(it) }

    @JvmStatic private external fun nativeInit(libDir: String)
    @JvmStatic private external fun nativeLoad(path: String, nCtx: Int, nThreads: Int): Long
    @JvmStatic private external fun nativeCount(h: Long, text: String): Int
    @JvmStatic private external fun nativeStop(h: Long)
    @JvmStatic private external fun nativeGenerate(h: Long, prompt: String, maxTokens: Int, temp: Float, topK: Int, topP: Float, minP: Float,
                                                   repeat: Float, presence: Float, seed: Int, sink: Sink): Int
    @JvmStatic private external fun nativeFree(h: Long)
    @JvmStatic private external fun nativeDescribe(model: String, mmproj: String, image: ByteArray, prompt: String, maxTokens: Int, sink: Sink): Int
}

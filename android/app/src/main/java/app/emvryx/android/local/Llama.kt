package app.emvryx.android.local

/**
 * The phone's own copy of llama.cpp (src/main/cpp/emvryx_llama.cpp): loads the model file and writes answers token by token.
 * Every call blocks, so callers run it off the main thread; one answer at a time.
 */
object Llama {
    /** Gives each piece of the answer (UTF-8 bytes); return false to stop */
    fun interface Sink {
        fun piece(bytes: ByteArray): Boolean
    }

    enum class End { Finished, Length, Stopped, TooLong, Failed }

    private var ready: Boolean? = null

    /** False on a phone the engine was not built for (it is built for 64-bit ARM phones, which is nearly all phones since 2017) */
    @Synchronized
    fun available(libDir: String): Boolean {
        ready?.let { return it }
        ready = try {
            System.loadLibrary("emvryx_llama")
            nativeInit(libDir)
            true
        } catch (e: Throwable) {
            false
        }
        return ready == true
    }

    class Model internal constructor(private var handle: Long) {
        fun count(text: String): Int = nativeCount(handle, text)

        fun stop() = nativeStop(handle)

        fun generate(prompt: String, maxTokens: Int, s: Map<String, Double>, sink: Sink): End {
            val r = nativeGenerate(
                handle, prompt, maxTokens,
                (s["temperature"] ?: 0.7).toFloat(), (s["top_k"] ?: 20.0).toInt(), (s["top_p"] ?: 0.8).toFloat(), (s["min_p"] ?: 0.0).toFloat(),
                (s["repeat_penalty"] ?: 1.0).toFloat(), (s["presence_penalty"] ?: 0.0).toFloat(), -1, sink,
            )
            return when (r) {
                0 -> End.Finished
                1 -> End.Length
                2 -> End.Stopped
                -1 -> End.TooLong
                else -> End.Failed
            }
        }

        fun close() {
            if (handle != 0L) nativeFree(handle)
            handle = 0
        }
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
}

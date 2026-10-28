// android_offline_model: the bridge between the app (local/Llama.kt) and llama.cpp. One model at a time; one answer at a time.
//
// The app writes the whole prompt (the chat format comes from the server, GET /api/phone-model); here it is turned into tokens, the part the model
// already read last time is kept (a follow-up question only reads what is new), and the answer comes back token by token as UTF-8 bytes.
#include <jni.h>
#include <atomic>
#include <cstring>
#include <string>
#include <vector>
#include <unistd.h>

#include "ggml-backend.h"
#include "llama.h"

#ifdef __ANDROID__
#include <android/log.h>
#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "emvryx-llama", __VA_ARGS__)
#else
#include <cstdio>
#define LOG(...) (fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
#endif

namespace {

struct Engine {
    llama_model *model = nullptr;
    llama_context *ctx = nullptr;
    const llama_vocab *vocab = nullptr;
    std::vector<llama_token> seen;            // the tokens the model has read and still holds (the start of the next prompt, most of the time)
    std::atomic<bool> stop{false};
    int batch = 512;
};

std::string utf8(JNIEnv *env, jstring s) {
    if (!s) return {};
    const char *c = env->GetStringUTFChars(s, nullptr);
    std::string out(c ? c : "");
    if (c) env->ReleaseStringUTFChars(s, c);
    return out;
}

std::vector<llama_token> tokenize(const llama_vocab *vocab, const std::string &text) {
    // parse_special: the chat format's markers (<|im_start|> ...) are real control tokens. The app has already made sure a person's own text
    // cannot contain one (Llama.kt cleans it), as the PC does with allow_special=False.
    int n = -llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), nullptr, 0, false, true);
    std::vector<llama_token> out(std::max(n, 0));
    if (n > 0 && llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), out.data(), n, false, true) < 0) out.clear();
    return out;
}

bool feed(Engine *e, llama_token *tokens, int n) {
    for (int i = 0; i < n; i += e->batch) {
        if (e->stop.load()) return false;
        int k = std::min(e->batch, n - i);
        if (llama_decode(e->ctx, llama_batch_get_one(tokens + i, k)) != 0) return false;
    }
    return true;
}

}  // namespace

extern "C" {

JNIEXPORT void JNICALL Java_app_emvryx_android_local_Llama_nativeInit(JNIEnv *env, jclass, jstring lib_dir) {
    std::string dir = utf8(env, lib_dir);
    if (!dir.empty()) ggml_backend_load_all_from_path(dir.c_str());     // the CPU code that suits this phone's chip
    else ggml_backend_load_all();
    llama_backend_init();
}

JNIEXPORT jlong JNICALL Java_app_emvryx_android_local_Llama_nativeLoad(JNIEnv *env, jclass, jstring path, jint n_ctx, jint n_threads) {
    llama_model_params mp = llama_model_default_params();
    std::string p = utf8(env, path);
    llama_model *model = llama_model_load_from_file(p.c_str(), mp);
    if (!model) return 0;
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = (uint32_t) n_ctx;
    cp.n_batch = 512;
    cp.n_ubatch = 512;
    int threads = n_threads > 0 ? n_threads : std::max(2, std::min(6, (int) sysconf(_SC_NPROCESSORS_ONLN) - 2));
    cp.n_threads = threads;
    cp.n_threads_batch = threads;
    llama_context *ctx = llama_init_from_model(model, cp);
    if (!ctx) {
        llama_model_free(model);
        return 0;
    }
    auto *e = new Engine();
    e->model = model;
    e->ctx = ctx;
    e->vocab = llama_model_get_vocab(model);
    LOG("loaded %s, context %d, %d threads", p.c_str(), n_ctx, threads);
    return reinterpret_cast<jlong>(e);
}

JNIEXPORT jint JNICALL Java_app_emvryx_android_local_Llama_nativeCount(JNIEnv *env, jclass, jlong h, jstring text) {
    auto *e = reinterpret_cast<Engine *>(h);
    return e ? (jint) tokenize(e->vocab, utf8(env, text)).size() : 0;
}

JNIEXPORT void JNICALL Java_app_emvryx_android_local_Llama_nativeStop(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (e) e->stop.store(true);
}

// Writes the answer to `prompt`, calling sink.piece(byte[]) for each token; sink.piece returns false to stop.
// Returns 0: finished (end of turn), 1: reached max_tokens, 2: stopped, -1: the prompt is too long, -2: the model failed.
JNIEXPORT jint JNICALL Java_app_emvryx_android_local_Llama_nativeGenerate(JNIEnv *env, jclass, jlong h, jstring jprompt, jint max_tokens,
                                                                         jfloat temp, jint top_k, jfloat top_p, jfloat min_p,
                                                                         jfloat repeat, jfloat presence, jint seed, jobject sink) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e) return -2;
    e->stop.store(false);
    jclass cls = env->GetObjectClass(sink);
    jmethodID piece = env->GetMethodID(cls, "piece", "([B)Z");
    if (!piece) return -2;

    std::vector<llama_token> prompt = tokenize(e->vocab, utf8(env, jprompt));
    const int n_ctx = (int) llama_n_ctx(e->ctx);
    if (prompt.empty() || (int) prompt.size() + 8 >= n_ctx) return -1;

    // keep what the model already read (the earlier turns), read only the rest
    size_t same = 0;
    while (same < e->seen.size() && same < prompt.size() - 1 && e->seen[same] == prompt[same]) same++;
    llama_memory_t mem = llama_get_memory(e->ctx);
    if (!llama_memory_seq_rm(mem, 0, (llama_pos) same, -1)) {            // a model whose memory cannot be cut back: read it all again
        llama_memory_clear(mem, true);
        same = 0;
    }
    e->seen.assign(prompt.begin(), prompt.begin() + (long) same);
    if (!feed(e, prompt.data() + same, (int) (prompt.size() - same))) {
        llama_memory_clear(mem, true);
        e->seen.clear();
        return e->stop.load() ? 2 : -2;
    }
    e->seen = prompt;

    llama_sampler_chain_params sp = llama_sampler_chain_default_params();
    llama_sampler *smpl = llama_sampler_chain_init(sp);
    if (repeat != 1.0f || presence != 0.0f)
        llama_sampler_chain_add(smpl, llama_sampler_init_penalties(llama_vocab_n_tokens(e->vocab), 64, repeat > 0 ? repeat : 1.0f, 0.0f, presence));
    if (top_k > 0) llama_sampler_chain_add(smpl, llama_sampler_init_top_k(top_k));
    if (top_p > 0 && top_p < 1) llama_sampler_chain_add(smpl, llama_sampler_init_top_p(top_p, 1));
    if (min_p > 0) llama_sampler_chain_add(smpl, llama_sampler_init_min_p(min_p, 1));
    if (temp <= 0) {
        llama_sampler_chain_add(smpl, llama_sampler_init_greedy());
    } else {
        llama_sampler_chain_add(smpl, llama_sampler_init_temp(temp));
        llama_sampler_chain_add(smpl, llama_sampler_init_dist(seed >= 0 ? (uint32_t) seed : LLAMA_DEFAULT_SEED));
    }

    int result = 1;
    char buf[256];
    for (int i = 0; i < max_tokens; i++) {
        if (e->stop.load()) { result = 2; break; }
        if ((int) e->seen.size() + 1 >= n_ctx) { result = 1; break; }
        llama_token t = llama_sampler_sample(smpl, e->ctx, -1);
        if (llama_vocab_is_eog(e->vocab, t)) { result = 0; break; }
        int n = llama_token_to_piece(e->vocab, t, buf, sizeof(buf), 0, true);
        if (n > 0) {
            jbyteArray bytes = env->NewByteArray(n);
            env->SetByteArrayRegion(bytes, 0, n, reinterpret_cast<const jbyte *>(buf));
            jboolean more = env->CallBooleanMethod(sink, piece, bytes);
            env->DeleteLocalRef(bytes);
            if (env->ExceptionCheck() || !more) { result = 2; break; }
        }
        if (llama_decode(e->ctx, llama_batch_get_one(&t, 1)) != 0) { result = -2; break; }
        e->seen.push_back(t);
    }
    llama_sampler_free(smpl);
    if (result == -2) {
        llama_memory_clear(mem, true);
        e->seen.clear();
    }
    return result;
}

JNIEXPORT void JNICALL Java_app_emvryx_android_local_Llama_nativeFree(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e) return;
    llama_free(e->ctx);
    llama_model_free(e->model);
    delete e;
}

}  // extern "C"

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
#include "mtmd.h"
#include "mtmd-helper.h"

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

// android_phone_vision: looks at one picture and writes what it shows (the PC's vision.py helper, on the phone). The picture model is loaded,
// used once and freed, so it never sits in the phone's memory next to the chat model. `prompt` is the instruction; the picture goes before it.
// Returns 0: finished, 1: reached max_tokens, 2: stopped, -1: the picture could not be read, -2: the model failed to load or run.
JNIEXPORT jint JNICALL Java_app_emvryx_android_local_Llama_nativeDescribe(JNIEnv *env, jclass, jstring jmodel, jstring jmmproj, jbyteArray jimage,
                                                                         jstring jprompt, jint max_tokens, jobject sink) {
    jclass cls = env->GetObjectClass(sink);
    jmethodID piece = env->GetMethodID(cls, "piece", "([B)Z");
    if (!piece) return -2;
    std::vector<unsigned char> image((size_t) env->GetArrayLength(jimage));
    env->GetByteArrayRegion(jimage, 0, (jsize) image.size(), reinterpret_cast<jbyte *>(image.data()));
    int threads = std::max(2, std::min(6, (int) sysconf(_SC_NPROCESSORS_ONLN) - 2));

    llama_model *model = llama_model_load_from_file(utf8(env, jmodel).c_str(), llama_model_default_params());
    if (!model) return -2;
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = 4096;
    cp.n_batch = 512;
    cp.n_ubatch = 512;
    cp.n_threads = threads;
    cp.n_threads_batch = threads;
    llama_context *ctx = llama_init_from_model(model, cp);
    mtmd_context_params mp = mtmd_context_params_default();
    mp.use_gpu = false;
    mp.print_timings = false;
    mp.warmup = false;
    mp.n_threads = threads;
    mp.image_max_tokens = 768;                    // a phone: fewer picture pieces read, a few seconds instead of a minute
    mtmd_context *mctx = ctx ? mtmd_init_from_file(utf8(env, jmmproj).c_str(), model, mp) : nullptr;
    auto done = [&](int r) {
        if (mctx) mtmd_free(mctx);
        if (ctx) llama_free(ctx);
        llama_model_free(model);
        return r;
    };
    if (!mctx || !mtmd_support_vision(mctx)) return done(-2);

    mtmd_helper_bitmap_wrapper bm = mtmd_helper_bitmap_init_from_buf(mctx, image.data(), image.size(), false, mtmd_helper_init_opt_default());
    if (!bm.bitmap) return done(-1);
    // the picture model's own chat format (it is in the file); ChatML when the file has none
    std::string user = std::string(mtmd_default_marker()) + "\n" + utf8(env, jprompt);
    llama_chat_message msg{"user", user.c_str()};
    std::string text;
    const char *tmpl = llama_model_chat_template(model, nullptr);
    int need = tmpl ? llama_chat_apply_template(tmpl, &msg, 1, true, nullptr, 0) : -1;
    if (need > 0) {
        text.resize((size_t) need);
        llama_chat_apply_template(tmpl, &msg, 1, true, text.data(), need);
    } else {
        text = "<|im_start|>user\n" + user + "<|im_end|>\n<|im_start|>assistant\n";
    }
    mtmd_input_chunks *chunks = mtmd_input_chunks_init();
    mtmd_input_text in{text.c_str(), text.size(), true, true};
    const mtmd_bitmap *bitmaps[] = {bm.bitmap};
    int tok = mtmd_tokenize(mctx, chunks, &in, bitmaps, 1);
    mtmd_bitmap_free(bm.bitmap);
    llama_pos n_past = 0;
    if (tok != 0 || (int) mtmd_helper_get_n_pos(chunks) + 16 >= (int) cp.n_ctx ||
        mtmd_helper_eval_chunks(mctx, ctx, chunks, 0, 0, (int32_t) cp.n_batch, true, &n_past) != 0) {
        mtmd_input_chunks_free(chunks);
        return done(tok == 2 ? -1 : -2);
    }
    mtmd_input_chunks_free(chunks);

    const llama_vocab *vocab = llama_model_get_vocab(model);
    llama_sampler *smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(smpl, llama_sampler_init_penalties(llama_vocab_n_tokens(vocab), 64, 1.05f, 0.0f, 0.0f));
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());     // describing, not inventing: always the likeliest word
    llama_batch one = llama_batch_init(1, 0, 1);
    int result = 1;
    char buf[256];
    for (int i = 0; i < max_tokens; i++) {
        if (n_past + 1 >= (llama_pos) cp.n_ctx) break;
        llama_token t = llama_sampler_sample(smpl, ctx, -1);
        if (llama_vocab_is_eog(vocab, t)) { result = 0; break; }
        int n = llama_token_to_piece(vocab, t, buf, sizeof(buf), 0, false);
        if (n > 0) {
            jbyteArray bytes = env->NewByteArray(n);
            env->SetByteArrayRegion(bytes, 0, n, reinterpret_cast<const jbyte *>(buf));
            jboolean more = env->CallBooleanMethod(sink, piece, bytes);
            env->DeleteLocalRef(bytes);
            if (env->ExceptionCheck() || !more) { result = 2; break; }
        }
        one.n_tokens = 1;
        one.token[0] = t;
        one.pos[0] = n_past++;
        one.n_seq_id[0] = 1;
        one.seq_id[0][0] = 0;
        one.logits[0] = true;
        if (llama_decode(ctx, one) != 0) { result = -2; break; }
    }
    llama_batch_free(one);
    llama_sampler_free(smpl);
    return done(result);
}

}  // extern "C"

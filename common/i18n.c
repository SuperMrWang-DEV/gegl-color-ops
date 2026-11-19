/* ===========================================================================
 * SuperMrWang · 多语言 / i18n plumbing
 * ---------------------------------------------------------------------------
 * 算子是被 GEGL 用 GModule 直接 dlopen 的，不经过 GIMP 的 main()，所以没有任何
 * 人替我们调用 bindtextdomain()。而 libintl 的默认目录是编译期写死的
 * （Windows 上实测是 /clang64/share/locale），把 .mo 丢进 GIMP 的 share/locale
 * 并不会被找到 —— 这一点必须自己绑，而且必须绑到我们自己算出来的目录。
 *
 * 这个文件单独成一个编译单元（build.sh 与 meson.build 都把它和每个算子一起
 * 编译），刻意不放进公共头：windows.h 的宏会污染算子源码（实测 rpcndr.h 里的
 * hyper 之类会把 GEGL_OP_C_SOURCE 的 "vibrance-hyper.c" 撑成 "vibrance-long long.c"）。
 *
 * 载入期构造函数会在 GEGL 创建算子实例、注册 GObject 属性之前跑，而算子里的
 * _() 都是类初始化时才求值，时序上安全。
 *
 * 候选目录（命中的第一个生效）：
 *   1. $LB_LOCALEDIR                  —— 开发 / 调试用的显式覆盖
 *   2. <模块目录>/locale              —— dist 里 .dll 与 locale 并排
 *   3. <模块目录>/../locale           —— 装到 GIMP 用户目录的常规布局
 *   4. <模块目录>/../share/locale     —— 装到 GIMP 前缀时的常规布局
 *
 * 绑定失败不报错、不影响运算：_() 会原样返回英文 msgid，也就是「英文兜底」。
 * =========================================================================== */

/* dladdr 在 glibc 里受 _GNU_SOURCE 控制；不定义时 -Wall 会给隐式声明警告 */
#ifndef _GNU_SOURCE
#  define _GNU_SOURCE 1
#endif

#include <glib.h>
#include <libintl.h>

#include "config.h"             /* GETTEXT_PACKAGE */

#if defined(G_OS_WIN32)
#  include <windows.h>
#elif !defined(__APPLE__)
#  include <dlfcn.h>            /* dladdr；glibc 2.34+ / musl 都在 libc 里 */
#endif

static gchar *
module_dir (void)
{
  gchar *dir = NULL;

#if defined(G_OS_WIN32)
  HMODULE mod = NULL;
  if (GetModuleHandleExW (GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                          GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                          (LPCWSTR) (const void *) &module_dir, &mod))
    {
      wchar_t buf[MAX_PATH];
      DWORD n = GetModuleFileNameW (mod, buf, G_N_ELEMENTS (buf));

      if (n > 0 && n < G_N_ELEMENTS (buf))
        {
          gchar *utf8 = g_utf16_to_utf8 ((const gunichar2 *) buf, -1,
                                         NULL, NULL, NULL);
          if (utf8)
            {
              dir = g_path_get_dirname (utf8);
              g_free (utf8);
            }
        }
    }
#elif !defined(__APPLE__)
  Dl_info info;

  if (dladdr ((void *) &module_dir, &info) && info.dli_fname)
    dir = g_path_get_dirname (info.dli_fname);
#endif

  return dir;
}

static void
bind_catalogs (void)
{
  const gchar *forced = g_getenv ("LB_LOCALEDIR");
  gchar *base, *cand[5];
  gint i;

  if (forced && g_file_test (forced, G_FILE_TEST_IS_DIR))
    {
      bindtextdomain (GETTEXT_PACKAGE, forced);
      return;
    }

  base = module_dir ();
  if (!base)
    return;

  cand[0] = g_build_filename (base, "locale", NULL);
  cand[1] = g_build_filename (base, "..", "locale", NULL);
  cand[2] = g_build_filename (base, "..", "share", "locale", NULL);
  cand[3] = NULL;

  for (i = 0; cand[i]; i++)
    {
      if (g_file_test (cand[i], G_FILE_TEST_IS_DIR))
        {
          bindtextdomain (GETTEXT_PACKAGE, cand[i]);
          break;
        }
    }

  for (i = 0; cand[i]; i++)
    g_free (cand[i]);
  g_free (base);
}

#if defined(__GNUC__) || defined(__clang__)
__attribute__((constructor))
static void
lb_i18n_init (void)
{
  bind_catalogs ();
}
#else
/* MSVC 没有构造属性；本工程不使用 MSVC 构建，这里仅作占位说明 */
#endif

/* ===========================================================================
 * SuperMrWang · 双输入算子测试 runner / two-input op test runner
 * ---------------------------------------------------------------------------
 * purpose    给 input + aux 两个 pad 各接一张图，跑一遍算子并存盘。gegl 命令
 *            行只支持单输入，没法测 lb:apply-image / lb:calculations，所以
 *            这里直接建 GEGL 图。
 *            Wires an image into both the input and aux pads, runs one op and
 *            writes the result. The gegl CLI takes a single input only, so the
 *            two-input ops cannot be driven from the command line.
 * usage      auxrun <out.png> <op> <in.png> <aux.png> [key=val ...]
 * note       key 用属性名（blend-mode），枚举给 nick（multiply），布尔给
 *            true/false；另有 aux-x / aux-y 把 aux 平移到指定位置，用来测
 *            「源层比主图小 / 不在原点」这类尺寸不匹配的情况。
 *            / Property names use kebab-case, enums take their nick,
 *            booleans take true/false. aux-x / aux-y translate the aux image,
 *            to test sources smaller than the target or off-origin.
 * license    GPL-3.0-or-later，见工程根目录 LICENSE
 * ========================================================================== */

#include <gegl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void
set_prop (GeglNode *node, const char *key, const char *val)
{
  GObject    *oper = G_OBJECT (gegl_node_get_gegl_operation (node));
  GParamSpec *ps   = g_object_class_find_property (G_OBJECT_GET_CLASS (oper), key);

  if (ps == NULL)
    {
      fprintf (stderr, "no property '%s'\n", key);
      return;
    }

  if (G_IS_PARAM_SPEC_ENUM (ps))
    {
      GEnumClass *ec = G_PARAM_SPEC_ENUM (ps)->enum_class;
      GEnumValue *ev = g_enum_get_value_by_nick (ec, val);

      if (ev == NULL)
        ev = g_enum_get_value_by_name (ec, val);

      if (ev != NULL)
        g_object_set (oper, key, ev->value, NULL);
      else
        fprintf (stderr, "bad enum value %s=%s\n", key, val);
    }
  else if (G_IS_PARAM_SPEC_BOOLEAN (ps))
    g_object_set (oper, key, g_ascii_strcasecmp (val, "true") == 0, NULL);
  else if (G_IS_PARAM_SPEC_DOUBLE (ps))
    g_object_set (oper, key, g_ascii_strtod (val, NULL), NULL);
  else if (G_IS_PARAM_SPEC_INT (ps))
    g_object_set (oper, key, atoi (val), NULL);
}

int
main (int argc, char **argv)
{
  if (argc < 5)
    {
      fprintf (stderr, "usage: auxrun <out.png> <op> <in.png> <aux.png> "
                       "[key=val ...]\n");
      return 2;
    }

  gegl_init (&argc, &argv);

  GeglNode *in  = gegl_node_new_child (NULL, "operation", "gegl:load",
                                       "path", argv[3], NULL);
  GeglNode *aux = gegl_node_new_child (NULL, "operation", "gegl:load",
                                       "path", argv[4], NULL);
  /* aux 先过一个 translate：aux-x / aux-y 用来模拟「源图层比主图层小、
   * 还不在原点」，这类图层的缓冲区 extent 才是算子真正该看的边界。
   * The aux goes through a translate node so aux-x / aux-y can emulate a
   * source layer that is smaller than the target and off-origin; that
   * buffer's extent is the boundary the op is supposed to respect. */
  GeglNode *aux_tr = gegl_node_new_child (NULL, "operation", "gegl:translate",
                                          NULL);
  GeglNode *op  = gegl_node_new_child (NULL, "operation", argv[2], NULL);
  GeglNode *sink = gegl_node_new_child (NULL, "operation", "gegl:save",
                                        "path", argv[1], NULL);

  for (int i = 5; i < argc; i++)
    {
      char *eq = strchr (argv[i], '=');

      if (eq == NULL)
        continue;

      *eq = '\0';
      if (g_strcmp0 (argv[i], "aux-x") == 0 || g_strcmp0 (argv[i], "aux-y") == 0)
        g_object_set (gegl_node_get_gegl_operation (aux_tr),
                      argv[i] + 4, g_ascii_strtod (eq + 1, NULL), NULL);
      else
        set_prop (op, argv[i], eq + 1);
    }

  gegl_node_link (in, op);
  gegl_node_link (aux, aux_tr);
  gegl_node_connect (aux_tr, "output", op, "aux");
  gegl_node_link (op, sink);

  gegl_node_process (sink);

  g_object_unref (op);
  g_object_unref (in);
  g_object_unref (aux);
  g_object_unref (aux_tr);
  g_object_unref (sink);
  gegl_exit ();
  return 0;
}

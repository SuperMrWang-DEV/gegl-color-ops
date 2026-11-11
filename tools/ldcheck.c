/* 临时诊断：在 Linux 上确认 .so 能被 GEGL 加载、注册，并跑一次恒等渲染 */
#include <gegl.h>
#include <stdio.h>
#include <string.h>

int main (int argc, char **argv)
{
  gegl_init (&argc, &argv);
  int bad = 0;
  for (int i = 1; i < argc; i++)
    if (!gegl_has_operation (argv[i]))
      {
        printf ("MISSING %s\n", argv[i]);
        bad++;
      }
  printf ("注册成功 %d/%d\n", argc - 1 - bad, argc - 1);

  const Babl *fmt = babl_format ("R~G~B~A float");
  GeglRectangle all = {0, 0, 4, 4};
  GeglRectangle one = {0, 0, 1, 1};
  gfloat px[4] = {200 / 255.0f, 120 / 255.0f, 60 / 255.0f, 1.0f};
  gfloat row[16];
  for (int i = 0; i < 4; i++)
    memcpy (row + i * 4, px, sizeof px);

  GeglBuffer *in  = gegl_buffer_new (&all, fmt);
  GeglBuffer *out = gegl_buffer_new (&all, fmt);
  gegl_buffer_set (in, &all, 0, fmt, row, 0);

  GeglNode *src  = gegl_node_new_child (NULL, "operation", "gegl:buffer-source",
                                        "buffer", in, NULL);
  GeglNode *node = gegl_node_new_child (NULL, "operation", "lb:channel-mixer-plus", NULL);
  GeglNode *sink = gegl_node_new_child (NULL, "operation", "gegl:write-buffer",
                                        "buffer", out, NULL);
  gegl_node_link_many (src, node, sink, NULL);
  gegl_node_process (sink);

  gfloat got[4] = {0};
  gegl_buffer_get (out, &one, 1.0, fmt, got, 0, GEGL_ABYSS_NONE);
  int d = 0;
  for (int k = 0; k < 3; k++)
    {
      int a = got[k] * 255 + 0.5, b = px[k] * 255 + 0.5;
      if ((a > b ? a - b : b - a) > 1)
        d++;
    }
  printf ("恒等渲染 4x4: in=(200,120,60) out=(%.0f,%.0f,%.0f) %s\n",
          got[0] * 255, got[1] * 255, got[2] * 255, d ? "FAIL" : "PASS");
  return bad + d;
}

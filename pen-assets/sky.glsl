#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

/** @resolution */
uniform vec2 u_resolution;

/**
 * @label Sky top
 * @color
 * @default #1C62C8
 */
uniform vec3 u_top;

/**
 * @label Sky middle
 * @color
 * @default #3C8FE4
 */
uniform vec3 u_mid;

/**
 * @label Sky bottom
 * @color
 * @default #6DB4F2
 */
uniform vec3 u_bottom;

/**
 * @label Light color
 * @color
 * @default #FFF6D6
 */
uniform vec3 u_light;

/**
 * @label Cloud color
 * @color
 * @default #FFFFFF
 */
uniform vec3 u_cloud;

/**
 * @label Light X
 * @default 0.85
 * @range 0, 1
 */
uniform float u_lightX;

/**
 * @label Light Y
 * @default 0.1
 * @range 0, 1
 */
uniform float u_lightY;

/**
 * @label Glow
 * @default 1
 * @range 0, 1
 */
uniform float u_sun;

/**
 * @label Rays
 * @default 1
 * @range 0, 1
 */
uniform float u_rays;

/**
 * @label Moon
 * @default 0
 * @range 0, 1
 */
uniform float u_moon;

/**
 * @label Stars
 * @default 0
 * @range 0, 1
 */
uniform float u_stars;

/**
 * @label Clouds
 * @default 0
 * @range 0, 1
 */
uniform float u_clouds;

/**
 * @label Rain
 * @default 0
 * @range 0, 1
 */
uniform float u_rain;

/**
 * @label Snow
 * @default 0
 * @range 0, 1
 */
uniform float u_snow;

/**
 * @label Moonlit
 * @default 0
 * @range 0, 1
 */
uniform float u_moonlit;

/**
 * @label Milky Way
 * @default 0
 * @range 0, 1
 */
uniform float u_milky;

/**
 * @label Sparkles
 * @default 0
 * @range 0, 1
 */
uniform float u_sparkle;

/**
 * @label Shade
 * @default 0
 * @range 0, 1
 */
uniform float u_shade;

/**
 * @label Seed
 * @default 1
 * @range 0, 50
 */
uniform float u_seed;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = p * 2.03 + vec2(17.1, 9.2);
    a *= 0.5;
  }
  return v;
}

// Slanted streaks: one random drop per cell of a tall, narrow grid.
float streaks(vec2 q, vec2 cell, float seed) {
  vec2 g = vec2(q.x + q.y * 0.2, q.y) / cell;
  float column = floor(g.x);
  g.y += hash(vec2(column, seed)) * 13.0;
  vec2 id = vec2(column, floor(g.y));
  vec2 f = fract(g);
  float on = step(0.64, hash(id + seed));
  float len = mix(0.35, 0.85, hash(id + seed + 3.3));
  float line = smoothstep(0.9, 0.15, abs(f.x - 0.5) * cell.x);
  float body = smoothstep(0.0, len * 0.6, f.y) * smoothstep(len, len - 0.12, f.y);
  return on * line * body;
}

// Snowflakes: one soft round flake per cell, jittered inside it.
float flakes(vec2 q, float cell, float seed) {
  vec2 g = vec2(q.x + q.y * 0.12, q.y) / cell;
  float column = floor(g.x);
  g.y += hash(vec2(column, seed)) * 13.0;
  vec2 id = vec2(column, floor(g.y));
  vec2 f = fract(g) - 0.5;
  vec2 o = (vec2(hash(id + seed + 1.3), hash(id + seed + 6.1)) - 0.5) * 0.7;
  float size = mix(0.06, 0.15, hash(id + seed + 3.3));
  float on = step(0.45, hash(id + seed));
  return on * smoothstep(size, size * 0.25, length(f - o));
}

// Stars: one per cell at most, most of them faint; a bright one has a soft halo.
float starfield(vec2 q, float cell, float chance, float seed) {
  vec2 g = q / cell;
  vec2 id = floor(g);
  vec2 o = (vec2(hash(id + seed + 1.7), hash(id + seed + 9.2)) - 0.5) * 0.7;
  float dist = length(fract(g) - 0.5 - o) * cell;
  float mag = pow(hash(id + seed + 4.4), 3.0);
  float core = smoothstep(0.6 + 0.6 * mag, 0.0, dist) * (0.3 + 0.7 * mag);
  float halo = exp(-dist * dist / (0.8 + 4.0 * mag)) * 0.3 * mag;
  return step(1.0 - chance, hash(id + seed)) * (core + halo);
}

// Sparkles: four-pointed stars, a concave diamond with a small glow in the middle.
float sparkles(vec2 q, float cell, float chance, float seed) {
  vec2 g = q / cell;
  vec2 id = floor(g);
  vec2 o = (vec2(hash(id + seed + 2.9), hash(id + seed + 7.3)) - 0.5) * 0.5;
  vec2 p = abs(fract(g) - 0.5 - o) * cell;
  float size = cell * mix(0.07, 0.17, hash(id + seed + 5.5));
  float shape = smoothstep(0.0, 0.22, 1.0 - (sqrt(p.x) + sqrt(p.y)) / sqrt(size));
  float halo = exp(-dot(p, p) / (size * size * 0.5)) * 0.35;
  return step(1.0 - chance, hash(id + seed)) * (shape + halo) * mix(0.55, 1.0, hash(id + seed + 8.8));
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  uv.y = 1.0 - uv.y;  // gl_FragCoord grows upwards; the layout below reads top to bottom
  float aspect = u_resolution.x / u_resolution.y;
  // Design pixels: the window is 300 wide whatever the zoom.
  vec2 q = uv * vec2(300.0, 300.0 / aspect);

  vec3 col = mix(u_top, u_mid, smoothstep(0.0, 0.58, uv.y));
  col = mix(col, u_bottom, smoothstep(0.42, 1.0, uv.y));

  // An overcast sky loses its colour.
  float overcast = clamp(max(u_clouds - 0.3, max(u_rain * 0.9, u_snow * 0.7)), 0.0, 1.0);
  float luma = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(col, vec3(luma) * vec3(0.78, 0.85, 0.97), overcast * 0.75);
  col *= 1.0 - 0.3 * u_rain;
  col *= 1.0 - 0.1 * u_snow;

  // Clouds gather at the top of the window. Their shape is worked out first:
  // by moonlight they hide the stars.
  vec2 cp = vec2(q.x * 0.0085, q.y * 0.019) + vec2(u_seed * 1.7, u_seed * 0.6);
  float n = fbm(cp) + (0.45 - uv.y) * 0.3;
  float threshold = mix(0.8, 0.3, u_clouds);
  float mask = smoothstep(threshold, threshold + 0.22, n) * step(0.001, u_clouds);
  float thick = smoothstep(threshold, threshold + 0.55, n);

  bool moonlit = u_moonlit > 0.5;
  float moonR = 0.062;
  vec3 sky = col;

  // Sun or moon: a glow and soft rays fanning out of it.
  vec2 d = (uv - vec2(u_lightX, u_lightY)) * vec2(aspect, 1.0);
  float r = length(d);
  float angle = atan(d.y, d.x);
  float glow = exp(-r * 2.6) * 0.5 + exp(-r * 9.0) * 0.7;
  if (moonlit) {
    // Moonlight comes off the lit limb rather than the middle of the disc.
    float lr = length(d - vec2(-0.88, 0.47) * moonR * 0.6);
    glow = exp(-lr * 16.0) * 0.6 + exp(-lr * 3.4) * 0.34;
  }
  float ray = (0.5 + 0.5 * sin(angle * 9.0 + u_seed)) * (0.5 + 0.5 * sin(angle * 17.0 + u_seed * 2.3 + 1.7));
  float rays = pow(ray, 1.3) * exp(-r * 1.2) * smoothstep(0.03, 0.3, r);
  float light = glow * u_sun + rays * u_rays * 0.95;
  col += u_light * light * (1.0 - col);

  // What only a clear night shows: clouds, the moon's disc and the horizon put it out.
  float clearNight = (1.0 - mask) * (1.0 - smoothstep(moonR * 1.3, moonR, r) * u_moon) * smoothstep(1.0, 0.3, uv.y);

  // Milky Way: a slanted band of dust with a dark lane along it and a crowd of faint stars.
  float across = dot(q - vec2(135.0, 0.0), vec2(0.8, -0.6));
  float band = exp(-across * across / 1800.0);
  float dust = fbm(q * 0.021 + u_seed * 2.3);
  float lane = smoothstep(0.42, 0.7, fbm(q * 0.034 + u_seed * 5.1)) * exp(-across * across / 300.0);
  float milky = band * (0.25 + dust) * (1.0 - 0.75 * lane);
  col += mix(u_light, vec3(1.0, 0.84, 0.92), 0.35) * milky * 0.25 * u_milky * clearNight;
  col += starfield(q + 7.0, 6.0, 0.55, u_seed + 8.0) * band * 0.7 * u_milky * clearNight;

  // Sparkles: more of them as the setting grows, the large ones only in its upper half.
  // They stay in the upper sky, clear of whatever is laid out below.
  float sparkle = sparkles(q, 46.0, 0.1 + 0.2 * u_sparkle, u_seed + 2.0)
    + sparkles(q + 23.0, 78.0, 0.35, u_seed + 6.0) * smoothstep(0.5, 1.0, u_sparkle);
  sparkle *= smoothstep(0.66, 0.36, uv.y);
  col = mix(col, mix(u_light, vec3(1.0), 0.5), clamp(sparkle, 0.0, 1.0) * clamp(u_sparkle * 4.0, 0.0, 1.0) * clearNight);

  if (moonlit) {
    // The clouds part around the moon.
    mask *= 1.0 - 0.8 * smoothstep(moonR * 2.4, moonR * 0.9, r) * u_moon;

    // A dust of faint stars and a few bright ones; clouds, the moon's glow
    // and the horizon put them out.
    float veil = (1.0 - mask) * (1.0 - 0.8 * exp(-r * 7.0) * u_moon) * smoothstep(1.0, 0.3, uv.y);
    float stars = starfield(q, 13.0, 0.35, u_seed) * 0.6 + starfield(q + 19.0, 44.0, 0.4, u_seed + 3.0);
    col += mix(vec3(1.0), u_light, 0.4) * stars * u_stars * veil;

    // Moon: a lit sphere, so the terminator is soft and the dark side barely shows.
    vec2 mp = d / moonR;
    float md = dot(mp, mp);
    float disc = smoothstep(1.06, 0.94, sqrt(md));
    vec3 normal = vec3(mp, sqrt(max(1.0 - md, 0.0)));
    float lit = smoothstep(-0.05, 0.2, dot(normal, vec3(-0.8, 0.44, -0.4)));
    float surface = 0.86 + 0.14 * smoothstep(0.35, 0.65, fbm(mp * 1.8 + u_seed));
    vec3 dark = sky + u_light * 0.07 + (col - sky) * 0.55;
    vec3 bright = mix(u_light, vec3(1.0), 0.35) * surface;
    col = mix(col, mix(dark, bright, lit), disc * u_moon);
  } else {
    // Stars thin out towards the horizon.
    vec2 sg = q / 15.0;
    vec2 sid = floor(sg);
    vec2 sf = fract(sg) - 0.5;
    float sh = hash(sid + u_seed);
    vec2 so = (vec2(hash(sid + 1.7), hash(sid + 9.2)) - 0.5) * 0.7;
    float star = smoothstep(0.03 + 0.07 * sh, 0.0, length(sf - so)) * step(0.7, sh);
    col += star * u_stars * (1.0 - uv.y * 0.85);

    // Crescent: a disc with a shifted disc cut out of it.
    float disc = smoothstep(moonR + 0.004, moonR - 0.004, r);
    float cut = smoothstep(moonR * 0.86 - 0.004, moonR * 0.86 + 0.004, length(d - vec2(0.034, -0.018)));
    col = mix(col, u_light, disc * cut * u_moon);
  }

  vec3 cloud = mix(u_cloud, u_cloud * 0.74, thick) * (1.0 - 0.32 * u_rain);
  if (moonlit) {
    // Near the moon the thin edges of a cloud shine and its body stays dark;
    // far from it the cloud is a shape barely lighter than the sky.
    float near = exp(-r * 3.5) * u_moon;
    cloud = mix(mix(u_cloud * 0.7, u_cloud * 0.5, thick), mix(u_light * 0.9, u_cloud * 0.8, thick), near);
  }
  cloud = mix(cloud, col, 0.22);
  col = mix(col, cloud, mask * 0.9);

  // Rain: two layers of streaks and a few drops on the glass.
  float rain = streaks(q, vec2(9.0, 46.0), u_seed) * 0.24 + streaks(q + 31.0, vec2(6.0, 30.0), u_seed + 7.0) * 0.1;
  col += rain * u_rain * vec3(0.85, 0.92, 1.0);

  vec2 dg = q / 34.0;
  vec2 did = floor(dg);
  vec2 df = fract(dg) - 0.5;
  vec2 dofs = (vec2(hash(did + 5.1), hash(did + 8.7)) - 0.5) * 0.6;
  float dr = mix(0.05, 0.13, hash(did + 2.2));
  float drop = smoothstep(dr, dr - 0.03, length((df - dofs) * vec2(1.0, 0.85))) * step(0.62, hash(did + u_seed + 20.0));
  float shine = smoothstep(dr * 0.55, 0.0, length(df - dofs + vec2(dr * 0.3, dr * 0.3)));
  col = mix(col, col * (0.8 + 0.25 * dot(col, vec3(0.333))), drop * u_rain);
  col += shine * drop * (0.05 + 0.25 * dot(col, vec3(0.333))) * u_rain;

  // Snow: three layers of flakes, the nearest ones large and out of focus.
  float snow = flakes(q, 11.0, u_seed) * 0.4 + flakes(q + 47.0, 19.0, u_seed + 5.0) * 0.7 + flakes(q + 113.0, 37.0, u_seed + 11.0) * 0.45;
  col = mix(col, vec3(0.95, 0.97, 1.0), clamp(snow, 0.0, 1.0) * u_snow);

  col *= 1.0 - u_shade;
  col += (hash(gl_FragCoord.xy) - 0.5) * 0.012;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}

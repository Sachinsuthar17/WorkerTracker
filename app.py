from flask import Flask, render_template, request, jsonify, Response, abort, send_from_directory
data = request.get_json(silent=True) or {}
token_id = data.get("token_id")
secret = data.get("secret")
scan_type = data.get("scan_type", "work")


if not token_id or not secret:
return jsonify({"status": "error", "message": "Missing token_id or secret"}), 400
if secret != DEVICE_SECRET:
return jsonify({"status": "error", "message": "Unauthorized"}), 403


conn = get_conn()
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("SELECT * FROM workers WHERE token_id=%s", (token_id,))
worker = cur.fetchone()
if not worker:
conn.close()
return jsonify({"status": "error", "message": "Invalid token_id"}), 404


cur.execute("INSERT INTO scan_logs (token_id, scan_type) VALUES (%s, %s)", (token_id, scan_type))


is_logged_in = worker["is_logged_in"]
if scan_type == "login":
cur.execute("UPDATE workers SET is_logged_in=TRUE, last_login=NOW() WHERE token_id=%s", (token_id,))
is_logged_in = True
message = "Login successful"
elif scan_type == "logout":
cur.execute("UPDATE workers SET is_logged_in=FALSE, last_logout=NOW() WHERE token_id=%s", (token_id,))
is_logged_in = False
message = "Logout successful"
else:
message = "Work scan logged"


cur.execute("""
SELECT COUNT(*) FROM scan_logs
WHERE token_id=%s AND scan_type='work' AND DATE(scanned_at)=CURRENT_DATE
""", (token_id,))
scans_today = cur.fetchone()[0]


conn.commit()
conn.close()


return jsonify({
"status": "success",
"message": message,
"name": worker["name"],
"department": worker["department"],
"is_logged_in": is_logged_in,
"scans_today": scans_today,
"earnings": scans_today * RATE_PER_PIECE,
})




# =============================
# MISC
# =============================
@app.route('/favicon.ico')
def favicon():
return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')




if __name__ == "__main__":
port = int(os.getenv("PORT", "5000"))
app.run(host="0.0.0.0", port=port)
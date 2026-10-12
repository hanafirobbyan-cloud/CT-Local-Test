-- Skema database (PostgreSQL), dihasilkan dari app/models.py.
-- Sumber kebenaran adalah migrasi Alembic di folder migrations/; file ini hanya referensi.

CREATE TABLE admin_users (
	id SERIAL NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	failed_logins INTEGER NOT NULL, 
	locked_until TIMESTAMP WITHOUT TIME ZONE, 
	last_login_at TIMESTAMP WITHOUT TIME ZONE, 
	session_nonce VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

CREATE TABLE audit_logs (
	id SERIAL NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	actor VARCHAR(64) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	target_type VARCHAR(40), 
	target_id VARCHAR(64), 
	details TEXT, 
	ip_hash VARCHAR(64), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE TABLE campaigns (
	id SERIAL NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	purpose VARCHAR(30) NOT NULL, 
	audience VARCHAR(20) NOT NULL, 
	custom_text TEXT, 
	scheduled_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_by VARCHAR(64), 
	enqueued_count INTEGER NOT NULL, 
	processed_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_campaigns_status ON campaigns (status);

CREATE TABLE integration_events (
	id SERIAL NOT NULL, 
	event VARCHAR(64) NOT NULL, 
	payload TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	next_attempt_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_error TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_integration_events_status ON integration_events (status);

CREATE TABLE participants (
	id SERIAL NOT NULL, 
	public_id VARCHAR(32) NOT NULL, 
	access_token VARCHAR(64) NOT NULL, 
	full_name VARCHAR(120) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	category VARCHAR(20) NOT NULL, 
	institution VARCHAR(150) NOT NULL, 
	student_id VARCHAR(30), 
	study_program VARCHAR(120), 
	city VARCHAR(80), 
	info_source VARCHAR(40), 
	status VARCHAR(20) NOT NULL, 
	privacy_consent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	consent_version VARCHAR(20) NOT NULL, 
	wa_consent BOOLEAN NOT NULL, 
	wa_consent_at TIMESTAMP WITHOUT TIME ZONE, 
	wa_opted_out_at TIMESTAMP WITHOUT TIME ZONE, 
	registered_ip_hash VARCHAR(64), 
	attended BOOLEAN NOT NULL, 
	attendance_method VARCHAR(20), 
	attendance_minutes INTEGER, 
	attended_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (public_id), 
	UNIQUE (access_token), 
	UNIQUE (email), 
	UNIQUE (phone)
);
CREATE INDEX ix_participants_attended ON participants (attended);
CREATE INDEX ix_participants_category ON participants (category);
CREATE INDEX ix_participants_status ON participants (status);

CREATE TABLE settings (
	key VARCHAR(64) NOT NULL, 
	value TEXT NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_by VARCHAR(64), 
	PRIMARY KEY (key)
);

CREATE TABLE certificates (
	id SERIAL NOT NULL, 
	participant_id INTEGER NOT NULL, 
	sequence INTEGER NOT NULL, 
	number VARCHAR(80) NOT NULL, 
	verify_code VARCHAR(32) NOT NULL, 
	download_token VARCHAR(64) NOT NULL, 
	file_name VARCHAR(200), 
	issued_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	generated_at TIMESTAMP WITHOUT TIME ZONE, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE, 
	revoke_reason VARCHAR(200), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (participant_id), 
	FOREIGN KEY(participant_id) REFERENCES participants (id) ON DELETE CASCADE, 
	UNIQUE (sequence), 
	UNIQUE (number), 
	UNIQUE (verify_code), 
	UNIQUE (download_token)
);

CREATE TABLE messages (
	id SERIAL NOT NULL, 
	participant_id INTEGER NOT NULL, 
	campaign_id INTEGER, 
	channel VARCHAR(10) NOT NULL, 
	purpose VARCHAR(30) NOT NULL, 
	dedupe_key VARCHAR(120), 
	status VARCHAR(20) NOT NULL, 
	provider VARCHAR(20), 
	provider_message_id VARCHAR(128), 
	body TEXT, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	scheduled_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	next_attempt_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_error TEXT, 
	sent_at TIMESTAMP WITHOUT TIME ZONE, 
	delivered_at TIMESTAMP WITHOUT TIME ZONE, 
	read_at TIMESTAMP WITHOUT TIME ZONE, 
	failed_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(participant_id) REFERENCES participants (id) ON DELETE CASCADE, 
	FOREIGN KEY(campaign_id) REFERENCES campaigns (id) ON DELETE SET NULL, 
	UNIQUE (dedupe_key)
);
CREATE INDEX ix_messages_campaign_id ON messages (campaign_id);
CREATE INDEX ix_messages_next_attempt_at ON messages (next_attempt_at);
CREATE INDEX ix_messages_participant_id ON messages (participant_id);
CREATE INDEX ix_messages_provider_message_id ON messages (provider_message_id);
CREATE INDEX ix_messages_purpose ON messages (purpose);
CREATE INDEX ix_messages_status ON messages (status);

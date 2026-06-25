SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS job_applications (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  company VARCHAR(120) NOT NULL COMMENT 'Company name',
  role VARCHAR(160) NOT NULL COMMENT 'Job role',
  channel VARCHAR(80) NOT NULL DEFAULT 'unknown' COMMENT 'Application channel',
  applied_at DATE NOT NULL COMMENT 'Application date',
  status VARCHAR(40) NOT NULL DEFAULT 'applied' COMMENT 'draft/applied/screening/interview/offer/rejected/withdrawn',
  city VARCHAR(80) DEFAULT NULL COMMENT 'Work city',
  salary_min INT DEFAULT NULL COMMENT 'Minimum monthly salary in CNY',
  salary_max INT DEFAULT NULL COMMENT 'Maximum monthly salary in CNY',
  notes TEXT COMMENT 'Notes',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_job_applications_status (status),
  INDEX idx_job_applications_applied_at (applied_at),
  INDEX idx_job_applications_company (company),
  INDEX idx_job_applications_channel (channel),
  INDEX idx_job_applications_status_applied_at (status, applied_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS application_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  application_id BIGINT NOT NULL,
  event_type VARCHAR(60) NOT NULL COMMENT 'screening/interview/hr_contact/offer/rejection/follow_up',
  event_at DATETIME NOT NULL,
  contact_name VARCHAR(120) DEFAULT NULL COMMENT 'HR or interviewer name',
  notes TEXT COMMENT 'Event notes',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_application_events_application
    FOREIGN KEY (application_id) REFERENCES job_applications(id)
    ON DELETE CASCADE,
  INDEX idx_application_events_application_id (application_id),
  INDEX idx_application_events_event_type (event_type),
  INDEX idx_application_events_event_at (event_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO job_applications
  (company, role, channel, applied_at, status, city, salary_min, salary_max, notes)
VALUES
  ('字节跳动', '后端开发实习生', '官网', CURRENT_DATE - INTERVAL 9 DAY, 'screening', '北京', 300, 450, 'Python/FastAPI/RAG 项目匹配度较高'),
  ('腾讯', 'AI 应用开发实习生', '内推', CURRENT_DATE - INTERVAL 6 DAY, 'interview', '深圳', 280, 420, '已约一面，重点准备 LangGraph 和 RAG'),
  ('阿里云', '智能体工程实习生', 'Boss 直聘', CURRENT_DATE - INTERVAL 4 DAY, 'applied', '杭州', 260, 400, 'JD 强调 Redis 和向量检索'),
  ('美团', '平台后端实习生', '拉勾', CURRENT_DATE - INTERVAL 2 DAY, 'rejected', '北京', 220, 350, '简历未通过，后续优化项目描述'),
  ('小红书', 'AI 产品研发实习生', '官网', CURRENT_DATE - INTERVAL 1 DAY, 'offer', '上海', 300, 500, '等待书面 offer')
ON DUPLICATE KEY UPDATE company = VALUES(company);

INSERT INTO application_events
  (application_id, event_type, event_at, contact_name, notes)
SELECT id, 'hr_contact', NOW() - INTERVAL 5 DAY, 'HR', '确认一面时间'
FROM job_applications
WHERE company = '腾讯'
LIMIT 1;

INSERT INTO application_events
  (application_id, event_type, event_at, contact_name, notes)
SELECT id, 'offer', NOW() - INTERVAL 1 DAY, 'HR', '口头 offer，等待书面材料'
FROM job_applications
WHERE company = '小红书'
LIMIT 1;

CREATE USER IF NOT EXISTS 'agent_reader'@'%' IDENTIFIED BY 'agent_reader_password';
GRANT SELECT ON personal_agent.job_applications TO 'agent_reader'@'%';
GRANT SELECT ON personal_agent.application_events TO 'agent_reader'@'%';
FLUSH PRIVILEGES;

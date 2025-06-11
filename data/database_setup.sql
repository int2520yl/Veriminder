
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;


-- --------------------------------------------------------
-- Table structure for table `bird_dev_topic_cluster`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `bird_dev_topic_cluster`;

CREATE TABLE `bird_dev_topic_cluster` (
  `id` int NOT NULL AUTO_INCREMENT,
  `cluster_name` varchar(1024) DEFAULT NULL,
  `cluster_key_attributes` json DEFAULT NULL,
  `cluster_quality_attributes` json DEFAULT NULL,
  `generative_algorithm` varchar(255) DEFAULT NULL,
  `question_features` json DEFAULT NULL,
  `table_features` json DEFAULT NULL,
  `associated_question_id_set` json DEFAULT NULL,
  `status` varchar(45) DEFAULT 'active',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `bird_dev_topic_cluster` (`id`, `cluster_name`) VALUES (2, 'California Educational Metrics Analysis');
INSERT INTO `bird_dev_topic_cluster` (`id`, `cluster_name`) VALUES (4, 'Card Game Database Attribute Queries');
INSERT INTO `bird_dev_topic_cluster` (`id`, `cluster_name`) VALUES (17, 'Toxicology Carcinogenicity Analysis Queries');


-- --------------------------------------------------------
-- Table structure for table `test_user`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `test_user`;

CREATE TABLE `test_user` (
  `id` int NOT NULL AUTO_INCREMENT,
  `prolific_user_id` varchar(255) DEFAULT NULL,
  `test_user_type` enum('type_1','type_2') DEFAULT 'type_1',
  `user_status` varchar(45) DEFAULT 'new',
  `created_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`),
  UNIQUE KEY `prolific_user_id_UNIQUE` (`prolific_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `test_user` (`id`, `prolific_user_id`, `test_user_type`) VALUES (101, 'analyst_01', 'type_2');


-- --------------------------------------------------------
-- Table structure for table `dataset`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `dataset`;

CREATE TABLE `dataset` (
  `id` int NOT NULL AUTO_INCREMENT,
  `question_id_from_BIRD` int DEFAULT NULL,
  `phase` tinyint DEFAULT '1',
  `question` json DEFAULT NULL,
  `decision` json DEFAULT NULL,
  `status` varchar(45) DEFAULT 'active',
  `version` tinyint DEFAULT '1',
  `question_to_sql_status` varchar(45) DEFAULT 'ready',
  `ai_only_response_status` varchar(45) DEFAULT 'ready',
  `perturbed_question_set_to_sql_status` varchar(45) DEFAULT 'ready',
  `post_hoc_summary_modification_status` varchar(45) DEFAULT 'ready',
  `post_hoc_summary_modification_with_checklist_status` varchar(45) DEFAULT 'ready',
  `with_critic_agent_input_status` varchar(45) DEFAULT 'ready',
  `baqr_status` varchar(45) DEFAULT 'ready',
  `source` varchar(45) DEFAULT 'prefilled',
  `is_assigned_for_level_2_batch_evaluation` tinyint DEFAULT '1',
  `is_assigned_for_level_1_ui_based_user_testing` tinyint DEFAULT '0',
  `test_user_id_1` int DEFAULT NULL,
  `test_user_id_2` int DEFAULT NULL,
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `dataset` (`id`, `question_id_from_BIRD`, `question`, `decision`) VALUES (1, 480, '{"text": "What is the highest eligible free rate for K-12 students in the schools in Alameda County?"}', '{"text": "Should the California Department of Education prioritize additional funding for Alameda County schools with the highest eligible free meal rates, or distribute resources equally across all schools in the county?"}');
INSERT INTO `dataset` (`id`, `question_id_from_BIRD`, `question`, `decision`) VALUES (2, 916450, '{"text": "Of all the cards that are designed by Aaron Miller, how many of them are incredibly powerful?"}', '{"text": "How effectively has Aaron Miller balanced power levels in his card designs, and should we continue to commission his work for cards intended to shape competitive play?"}');
INSERT INTO `dataset` (`id`, `question_id_from_BIRD`, `question`, `decision`) VALUES (3, 2074204, '{"text": "Of the first 100 molecules in number order, how many are carcinogenic?"}', '{"text": "A quality control specialist needs to determine if their molecular database has a representative distribution of carcinogenic compounds by examining the first 100 entries, assuming the database was populated in a random order."}');


-- --------------------------------------------------------
-- Table structure for table `bird_question_linked_to_cluster`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `bird_question_linked_to_cluster`;

CREATE TABLE `bird_question_linked_to_cluster` (
  `id` int NOT NULL AUTO_INCREMENT,
  `bird_question_id` int NOT NULL,
  `question_text` varchar(2048) DEFAULT NULL,
  `cluster_id` int DEFAULT NULL,
  `case_study_type` enum('choice','evaluation','diagnosis') DEFAULT NULL,
  `decision_text` varchar(2048) DEFAULT NULL,
  `status` varchar(45) DEFAULT 'pending',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `why_decision_question_pair_included` json DEFAULT NULL,
  `quality_score_for_inclusion` enum('BEST_MUST_INCLUDE','WILL_BE_GOOD_CANDIDATE','OK_TO_INCLUDE','INCLUDE_ONLY_AFTER_REVIEW') NOT NULL DEFAULT 'INCLUDE_ONLY_AFTER_REVIEW',
  PRIMARY KEY (`id`),
  KEY `to_cluster` (`cluster_id`),
  CONSTRAINT `to_cluster` FOREIGN KEY (`cluster_id`) REFERENCES `bird_dev_topic_cluster` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `bird_question_linked_to_cluster` (`id`, `bird_question_id`, `cluster_id`, `case_study_type`, `question_text`, `decision_text`, `quality_score_for_inclusion`) VALUES (1, 480, 2, 'choice', 'What is the highest eligible free rate for K-12 students in the schools in Alameda County?', 'Should the California Department of Education prioritize additional funding for Alameda County schools with the highest eligible free meal rates, or distribute resources equally across all schools in the county?', 'BEST_MUST_INCLUDE');
INSERT INTO `bird_question_linked_to_cluster` (`id`, `bird_question_id`, `cluster_id`, `case_study_type`, `question_text`, `decision_text`, `quality_score_for_inclusion`) VALUES (2, 916450, 4, 'evaluation', 'Of all the cards that are designed by Aaron Miller, how many of them are incredibly powerful?', 'How effectively has Aaron Miller balanced power levels in his card designs, and should we continue to commission his work for cards intended to shape competitive play?', 'BEST_MUST_INCLUDE');
INSERT INTO `bird_question_linked_to_cluster` (`id`, `bird_question_id`, `cluster_id`, `case_study_type`, `question_text`, `decision_text`, `quality_score_for_inclusion`) VALUES (3, 2074204, 17, 'evaluation', 'Of the first 100 molecules in number order, how many are carcinogenic?', 'A quality control specialist needs to determine if their molecular database has a representative distribution of carcinogenic compounds by examining the first 100 entries, assuming the database was populated in a random order.', 'BEST_MUST_INCLUDE');


-- --------------------------------------------------------
-- Table structure for table `baqr_prompt_template`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `baqr_prompt_template`;

CREATE TABLE `baqr_prompt_template` (
  `id` int NOT NULL AUTO_INCREMENT,
  `prompt_version_name` varchar(255) DEFAULT NULL,
  `source` varchar(45) DEFAULT NULL,
  `key_focus` json DEFAULT NULL,
  `approach_summary` json DEFAULT NULL,
  `steps_flow` json DEFAULT NULL,
  `detailed_prompt` json DEFAULT NULL,
  `status` varchar(45) DEFAULT NULL,
  `version` tinyint DEFAULT '1',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `baqr_prompt_template` (`id`, `prompt_version_name`, `status`) VALUES (1, 'Argument-Driven Inquiry', 'active');
INSERT INTO `baqr_prompt_template` (`id`, `prompt_version_name`, `status`) VALUES (2, 'Cognitive Bias Hunter', 'active');


-- --------------------------------------------------------
-- Table structure for table `baqr_critic_template`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `baqr_critic_template`;

CREATE TABLE `baqr_critic_template` (
  `id` int NOT NULL AUTO_INCREMENT,
  `critic_version_name` varchar(255) DEFAULT NULL,
  `source` varchar(45) DEFAULT NULL,
  `key_focus` json DEFAULT NULL,
  `approach_summary` json DEFAULT NULL,
  `steps_flow` json DEFAULT NULL,
  `detailed_prompt` json DEFAULT NULL,
  `status` varchar(45) DEFAULT NULL,
  `version` tinyint DEFAULT NULL,
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `baqr_critic_template` (`id`, `critic_version_name`, `status`) VALUES (1, 'Pragmatic Critic', 'active');
INSERT INTO `baqr_critic_template` (`id`, `critic_version_name`, `status`) VALUES (2, 'Skeptical Critic', 'active');


-- --------------------------------------------------------
-- Table structure for table `user_type_2_evaluation_dataset`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `user_type_2_evaluation_dataset`;

CREATE TABLE `user_type_2_evaluation_dataset` (
  `id` int NOT NULL AUTO_INCREMENT,
  `dataset_id` int NOT NULL,
  `model_1_questions` json DEFAULT NULL,
  `model_2_questions` json DEFAULT NULL,
  `model_3_questions` json DEFAULT NULL,
  `model_4_questions` json DEFAULT NULL,
  `model_5_questions` json DEFAULT NULL,
  `assigned_user_id_1` int DEFAULT NULL,
  `assigned_user_id_2` int DEFAULT NULL,
  `assigned_user_id_3` int DEFAULT NULL,
  `assigned_user_id_4` int DEFAULT NULL,
  `user_id_1_score` json DEFAULT NULL,
  `user_id_2_score` json DEFAULT NULL,
  `user_id_3_score` json DEFAULT NULL,
  `user_id_4_score` json DEFAULT NULL,
  `status` varchar(45) DEFAULT 'active',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
   PRIMARY KEY (`id`),
   UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `user_type_2_evaluation_dataset` (`id`, `dataset_id`, `assigned_user_id_1`, `status`) VALUES (1, 1, 101, 'active');


-- --------------------------------------------------------
-- Table structure for table `query`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `query`;

CREATE TABLE `query` (
  `id` int NOT NULL AUTO_INCREMENT,
  `dataset_id` int NOT NULL,
  `query_model` enum('question_to_sql','ai_only_response','perturbed_question_set_to_sql','post_hoc_summary_modification','post_hoc_summary_modification_with_checklist','baqr','with_critic_agent_input') NOT NULL DEFAULT 'question_to_sql',
  `NL_question` varchar(1024) DEFAULT NULL,
  `model_query_sequence_index` tinyint DEFAULT '1',
  `framework_details` json DEFAULT NULL,
  `framework_contribution_factor_name` varchar(255) DEFAULT NULL,
  `current_sql_options` json DEFAULT NULL,
  `execution_details` json DEFAULT NULL,
  `sql_generation_status` varchar(45) DEFAULT 'pending',
  `execution_status` varchar(45) DEFAULT NULL,
  `status` varchar(45) DEFAULT 'active',
  `version` tinyint DEFAULT '1',
  `COT_details` json DEFAULT NULL,
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `prompt_version_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;



-- --------------------------------------------------------
-- Table structure for table `summary_analysis`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `summary_analysis`;

CREATE TABLE `summary_analysis` (
  `id` int NOT NULL AUTO_INCREMENT,
  `dataset_id` int DEFAULT NULL,
  `evaluation_model` enum('question_to_sql','ai_only_response','perturbed_question_set_to_sql','post_hoc_summary_modification','post_hoc_summary_modification_with_checklist','baqr','with_critic_agent_input') DEFAULT 'question_to_sql',
  `prompt_details` json DEFAULT NULL,
  `summary` json DEFAULT NULL,
  `query_id_details` json DEFAULT NULL,
  `query_execution_details` json DEFAULT NULL,
  `prompt_status` varchar(45) DEFAULT NULL,
  `status` varchar(45) DEFAULT NULL,
  `version` tinyint DEFAULT '1',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;



-- --------------------------------------------------------
-- Table structure for table `level_1_evaluation`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `level_1_evaluation`;

CREATE TABLE `level_1_evaluation` (
  `id` int NOT NULL AUTO_INCREMENT,
  `dataset_id` int NOT NULL,
  `user_id` int NOT NULL,
  `solution_score` json DEFAULT NULL,
  `status` varchar(45) DEFAULT 'active',
  `ui_version` tinyint DEFAULT '1',
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;



-- --------------------------------------------------------
-- Table structure for table `baqr_prompt_template_nl_questions`
-- --------------------------------------------------------
DROP TABLE IF EXISTS `baqr_prompt_template_nl_questions`;

CREATE TABLE `baqr_prompt_template_nl_questions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `baqr_prompt_template_id` int NOT NULL,
  `bird_question_linked_to_cluster_id` int NOT NULL,
  `refinement_question_with_explanation_set` json DEFAULT NULL,
  `feedback_from_critic_1` json DEFAULT NULL,
  `feedback_from_critic_2` json DEFAULT NULL,
  `reflection_on_strength_weakness_of_prompt` json DEFAULT NULL,
  `last_updated_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `status` varchar(45) DEFAULT 'pending_critic',
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


SET FOREIGN_KEY_CHECKS = 1;

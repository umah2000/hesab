-- NEXTCAM: database and login, run ONCE in SQL Server Management Studio as sysadmin,
-- before deploy\windows\install.ps1. Replace the password (it goes into the installer
-- prompt, never into a file in git). SQL Server 2019 or later.
--
-- Least privilege for the program's login:
--   db_owner on its own database   schema migrations, triggers, RCSI (migration 0005)
--   dbcreator                       the weekly restore test restores a scratch copy
--                                   (<db>_restore_test) and drops it again
--   SELECT on two msdb tables       size of the backup it has just written

CREATE DATABASE nextcam;
GO
ALTER DATABASE nextcam SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
CREATE LOGIN nextcam_app WITH PASSWORD = N'<a long random password>', CHECK_POLICY = ON, DEFAULT_DATABASE = nextcam;
GO
ALTER SERVER ROLE dbcreator ADD MEMBER nextcam_app;
GO
USE nextcam;
CREATE USER nextcam_app FOR LOGIN nextcam_app;
ALTER ROLE db_owner ADD MEMBER nextcam_app;
GO
USE msdb;
CREATE USER nextcam_app FOR LOGIN nextcam_app;
GRANT SELECT ON dbo.backupset TO nextcam_app;
GRANT SELECT ON dbo.backupmediafamily TO nextcam_app;
GO

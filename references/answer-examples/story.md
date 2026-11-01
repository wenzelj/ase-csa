## B1 Story wording (good)
Facts:
- The SQL Server nodes take their time from the Windows Time client. (E-0210) {observed; HOSTCLU01, HOSTCLU03}
Story: The SQL Server nodes take their time from the Windows Time client. The captures show no local or application-supplied time source.

## B2 Story wording (bad: STORY_INFERS and STORY_STATES_RATING)
Facts:
- The SQL Server nodes take their time from the Windows Time client. (E-0210) {observed; HOSTCLU01, HOSTCLU03}
Story: The nodes use the Windows Time client, so their time comes from it rather than a local source. That gap decided this rating.

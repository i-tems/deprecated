const appName = import.meta.env.VITE_APP_NAME?.trim() || 'Hive'
const loginSubtitle =
  import.meta.env.VITE_APP_LOGIN_SUBTITLE?.trim() || 'Google 계정으로 로그인하세요'

export const branding = {
  appName,
  loginSubtitle,
  titleSuffix: import.meta.env.VITE_APP_TITLE_SUFFIX?.trim() || appName,
}

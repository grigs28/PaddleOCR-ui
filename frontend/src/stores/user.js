import { defineStore } from 'pinia'
import axios from 'axios'

export const useUserStore = defineStore('user', {
  state: () => ({ info: null, loaded: false }),
  getters: {
    isAdmin: (state) => state.info?.is_admin === 1,
    displayName: (state) => state.info?.display_name || '用户',
  },
  actions: {
    async fetchUser() {
      try {
        const { data } = await axios.get('/auth/me')
        this.info = data
      } catch {
        this.info = null
      }
      this.loaded = true
    },
  },
})
